"use client";

import { useEffect, useRef, useState } from "react";
import {
  AreaSeries,
  CandlestickSeries,
  ColorType,
  createChart,
  type IChartApi,
  type ISeriesApi,
  type UTCTimestamp,
} from "lightweight-charts";
import { fetchCandles, fetchHistory, WS_URL } from "@/lib/api";
import { useCssVars } from "@/lib/hooks";

export type LiveStats = {
  status: "connecting" | "live" | "reconnecting";
  first: number | null;
  last: number | null;
  high: number | null;
  low: number | null;
};

export type ChartMode = { kind: "line" } | { kind: "candles"; seconds: number };

const TICK_POINTS = 900;
const CANDLES = 240;
const TOKENS = ["surface", "muted", "grid", "axis", "series-1", "good", "critical"] as const;

type Candle = { time: UTCTimestamp; open: number; high: number; low: number; close: number };

function withAlpha(hex: string, alpha: number): string {
  const h = hex.replace("#", "");
  if (h.length !== 6) return hex;
  const [r, g, b] = [0, 2, 4].map((i) => parseInt(h.slice(i, i + 2), 16));
  return `rgba(${r}, ${g}, ${b}, ${alpha})`;
}

/**
 * Live price chart. The parent remounts it (via `key`) when the mode changes, so the
 * series type is fixed for the component's lifetime; symbol changes reload in place.
 */
export function LiveChart({
  symbol,
  decimals,
  mode,
  onStats,
}: {
  symbol: string;
  decimals: number;
  mode: ChartMode;
  onStats: (stats: LiveStats) => void;
}) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const seriesRef = useRef<ISeriesApi<"Area"> | ISeriesApi<"Candlestick"> | null>(null);
  const [ready, setReady] = useState(false);
  const colors = useCssVars(TOKENS);
  const hasColors = colors !== null;
  const onStatsRef = useRef(onStats);
  useEffect(() => {
    onStatsRef.current = onStats;
  });
  const candleSeconds = mode.kind === "candles" ? mode.seconds : 0;

  useEffect(() => {
    if (!containerRef.current || !hasColors) return;
    const chart = createChart(containerRef.current, {
      autoSize: true,
      layout: { fontFamily: "system-ui, -apple-system, Segoe UI, sans-serif", fontSize: 11 },
      timeScale: { timeVisible: true, secondsVisible: candleSeconds === 0, rightOffset: 6 },
      rightPriceScale: { scaleMargins: { top: 0.12, bottom: 0.08 } },
      localization: {
        timeFormatter: (t: number) =>
          new Date(t * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: candleSeconds ? undefined : "2-digit" }),
      },
    });
    chartRef.current = chart;
    seriesRef.current = candleSeconds
      ? chart.addSeries(CandlestickSeries, { borderVisible: false })
      : chart.addSeries(AreaSeries, { lineWidth: 2 });
    setReady(true);
    return () => {
      chart.remove();
      chartRef.current = null;
      seriesRef.current = null;
      setReady(false);
    };
  }, [hasColors, candleSeconds]);

  useEffect(() => {
    if (!colors || !chartRef.current || !seriesRef.current) return;
    chartRef.current.applyOptions({
      layout: { background: { type: ColorType.Solid, color: colors.surface }, textColor: colors.muted },
      grid: { vertLines: { color: withAlpha(colors.grid, 0.6) }, horzLines: { color: colors.grid } },
      rightPriceScale: { borderColor: colors.axis },
      timeScale: { borderColor: colors.axis },
      crosshair: { vertLine: { color: colors.muted }, horzLine: { color: colors.muted } },
    });
    if (candleSeconds) {
      (seriesRef.current as ISeriesApi<"Candlestick">).applyOptions({
        upColor: colors.good,
        downColor: colors.critical,
        wickUpColor: colors.good,
        wickDownColor: colors.critical,
      });
    } else {
      (seriesRef.current as ISeriesApi<"Area">).applyOptions({
        lineColor: colors["series-1"],
        topColor: withAlpha(colors["series-1"], 0.2),
        bottomColor: withAlpha(colors["series-1"], 0.01),
        priceLineColor: colors["series-1"],
      });
    }
  }, [colors, ready, candleSeconds]);

  // Load history, then stream live ticks. On any disconnect, reload from scratch
  // so the chart re-syncs with the server (e.g. after a backend restart).
  useEffect(() => {
    const series = seriesRef.current;
    const chart = chartRef.current;
    if (!ready || !series || !chart) return;
    series.applyOptions({ priceFormat: { type: "price", precision: decimals, minMove: 10 ** -decimals } });

    let cancelled = false;
    let ws: WebSocket | null = null;
    let retry: ReturnType<typeof setTimeout> | undefined;
    let abort: AbortController | null = null;

    const load = () => {
      let loaded = false;
      let lastT = 0;
      let candle: Candle | null = null;
      const stats: LiveStats = { status: "connecting", first: null, last: null, high: null, low: null };
      const pending: { epoch: number; quote: number }[] = [];
      onStatsRef.current({ ...stats });

      const apply = (t: number, v: number, push: boolean) => {
        if (t <= lastT) return;
        lastT = t;
        if (candleSeconds) {
          const bucket = (Math.floor(t / candleSeconds) * candleSeconds) as UTCTimestamp;
          if (candle && bucket === candle.time) {
            candle = { ...candle, high: Math.max(candle.high, v), low: Math.min(candle.low, v), close: v };
          } else {
            candle = { time: bucket, open: v, high: v, low: v, close: v };
          }
          (series as ISeriesApi<"Candlestick">).update(candle);
        } else {
          (series as ISeriesApi<"Area">).update({ time: t as UTCTimestamp, value: v });
        }
        stats.last = v;
        stats.high = stats.high === null ? v : Math.max(stats.high, v);
        stats.low = stats.low === null ? v : Math.min(stats.low, v);
        if (push) onStatsRef.current({ ...stats });
      };

      const finish = () => {
        loaded = true;
        pending.forEach((m) => apply(m.epoch, m.quote, false));
        chart.timeScale().fitContent();
        stats.status = "live";
        onStatsRef.current({ ...stats });
      };

      ws = new WebSocket(`${WS_URL}/ws/ticks/${encodeURIComponent(symbol)}`);
      ws.onmessage = (e) => {
        const msg = JSON.parse(e.data);
        if (msg.type !== "tick") return;
        if (loaded) apply(msg.epoch, msg.quote, true);
        else pending.push(msg);
      };
      ws.onclose = () => {
        if (cancelled) return;
        onStatsRef.current({ ...stats, status: "reconnecting" });
        retry = setTimeout(load, 2000);
      };

      abort = new AbortController();
      const request = candleSeconds
        ? fetchCandles(symbol, candleSeconds, CANDLES, abort.signal).then(({ points }) => {
            if (cancelled || !points.length) return;
            const data: Candle[] = points.map((p) => ({ time: p.t as UTCTimestamp, open: p.o, high: p.h, low: p.l, close: p.c }));
            (series as ISeriesApi<"Candlestick">).setData(data);
            candle = data[data.length - 1];
            // Ticks inside the last candle's bucket are already counted in it.
            lastT = points[points.length - 1].t + candleSeconds - 1;
            Object.assign(stats, {
              first: data[0].open,
              last: candle.close,
              high: Math.max(...data.map((c) => c.high)),
              low: Math.min(...data.map((c) => c.low)),
            });
            finish();
          })
        : fetchHistory(symbol, TICK_POINTS, abort.signal).then(({ points }) => {
            if (cancelled || !points.length) return;
            (series as ISeriesApi<"Area">).setData(points.map((p) => ({ time: p.t as UTCTimestamp, value: p.v })));
            const values = points.map((p) => p.v);
            lastT = points[points.length - 1].t;
            Object.assign(stats, { first: values[0], last: values[values.length - 1], high: Math.max(...values), low: Math.min(...values) });
            finish();
          });
      request.catch(() => {
        /* the websocket close handler schedules the retry */
      });
    };

    series.setData([]);
    load();
    return () => {
      cancelled = true;
      clearTimeout(retry);
      abort?.abort();
      if (ws) {
        ws.onclose = null;
        ws.close();
      }
    };
  }, [symbol, decimals, ready, candleSeconds]);

  return <div ref={containerRef} className="h-full w-full" aria-label={`Live price chart for ${symbol}`} role="img" />;
}
