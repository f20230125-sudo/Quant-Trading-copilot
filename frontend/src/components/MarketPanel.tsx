"use client";

import { useState } from "react";
import { ChartCandlestick, ChartLine, Dices, FlaskConical, Layers, Route, Waves } from "lucide-react";
import { LiveChart, type ChartMode, type LiveStats } from "./LiveChart";
import { Change, Chip, Segmented } from "./ui";
import { price, vol } from "@/lib/format";
import type { SnapshotRow, SymbolInfo } from "@/lib/types";

const CATEGORY: Record<string, string> = {
  volatility: "Volatility index",
  jump: "Jump index",
  crash_boom: "Crash / Boom",
  step: "Step index",
  regime: "Regime switching",
  momentum: "Momentum",
};

type ModeKey = "line" | "c60" | "c300";
const MODES: Record<ModeKey, ChartMode> = {
  line: { kind: "line" },
  c60: { kind: "candles", seconds: 60 },
  c300: { kind: "candles", seconds: 300 },
};

function Stat({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="min-w-0 px-4 py-3" title={hint}>
      <dt className="truncate text-[11px] text-muted">{label}</dt>
      <dd className="truncate text-sm font-medium text-ink tabular">{value}</dd>
    </div>
  );
}

export function MarketPanel({
  info,
  snapshot,
  onAsk,
}: {
  info: SymbolInfo | undefined;
  snapshot: SnapshotRow | undefined;
  onAsk: (prompt: string) => void;
}) {
  const [stats, setStats] = useState<LiveStats>({ status: "connecting", first: null, last: null, high: null, low: null });
  const [mode, setMode] = useState<ModeKey>("line");
  const change = stats.first && stats.last ? stats.last / stats.first - 1 : null;

  if (!info) {
    return <section className="panel min-h-[420px] flex-1 animate-pulse" aria-busy="true" aria-label="Loading market" />;
  }
  const s = info.symbol;
  const actions = [
    { icon: Waves, label: "Volatility", prompt: info.design_vol ? `How volatile is ${s} right now compared with its design?` : `How volatile is ${s} right now?` },
    { icon: Layers, label: "Regimes", prompt: `Does ${s} have distinct volatility regimes?` },
    { icon: FlaskConical, label: "Backtest SMA 20/50", prompt: `Backtest a 20/50 SMA crossover on ${s}` },
    { icon: Route, label: "Walk-forward", prompt: `Optimise a breakout strategy on ${s} with walk-forward` },
    { icon: Dices, label: "Will it go up?", prompt: `Will ${s} go up over the next hour?` },
  ];

  return (
    <section className="panel flex min-h-0 flex-1 flex-col overflow-hidden" aria-label={`${s} market`}>
      <header className="flex flex-wrap items-start justify-between gap-x-6 gap-y-3 px-5 pb-2 pt-4">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <h2 className="text-lg font-semibold tracking-tight text-ink">{s}</h2>
            <span className="text-sm text-ink-2">{info.name}</span>
            <Chip>{CATEGORY[info.category] ?? info.category}</Chip>
            <span className="inline-flex items-center gap-1.5 text-[11px] font-medium text-ink-2" role="status" aria-live="polite">
              <span
                className={`inline-block h-1.5 w-1.5 rounded-full ${stats.status === "live" ? "live-dot bg-good" : "bg-warning"}`}
                aria-hidden
              />
              {stats.status === "live" ? "Live" : stats.status === "reconnecting" ? "Reconnecting…" : "Connecting…"}
            </span>
          </div>
          <div className="mt-1.5 flex flex-wrap items-baseline gap-x-3 gap-y-1">
            <span className="text-3xl font-semibold tracking-tight text-ink">{price(stats.last, info.decimals)}</span>
            <Change value={change} digits={3} className="text-sm font-medium" />
            <span className="text-xs text-muted">in view</span>
          </div>
          <p className="mt-1 max-w-xl text-[13px] text-ink-2">{info.description}</p>
        </div>
        <Segmented
          label="Chart type"
          value={mode}
          onChange={setMode}
          options={[
            { value: "line", label: <><ChartLine size={13} aria-hidden /> Ticks</>, title: "Every tick, last 30 minutes or so" },
            { value: "c60", label: <><ChartCandlestick size={13} aria-hidden /> 1m</>, title: "1-minute candles" },
            { value: "c300", label: <><ChartCandlestick size={13} aria-hidden /> 5m</>, title: "5-minute candles" },
          ]}
        />
      </header>

      <div className="h-[300px] min-h-0 px-2 sm:h-[360px] lg:h-auto lg:min-h-[260px] lg:flex-1">
        <LiveChart key={mode} symbol={s} decimals={info.decimals} mode={MODES[mode]} onStats={setStats} />
      </div>

      <dl className="grid grid-cols-3 divide-line border-t border-line sm:grid-cols-5 sm:divide-x">
        <Stat label="High (in view)" value={price(stats.high, info.decimals)} />
        <Stat label="Low (in view)" value={price(stats.low, info.decimals)} />
        <Stat label="Realized vol (30m)" value={snapshot ? vol(snapshot.realized_vol) : "–"} hint="Annualised, from the last 30 minutes of ticks" />
        <Stat label="Design vol" value={info.design_vol ? vol(info.design_vol) : "n/a"} hint="The volatility the process is built with" />
        <Stat label="Tick interval" value={`${info.tick_interval_s}s`} />
      </dl>

      <div className="flex flex-wrap items-center gap-2 border-t border-line px-4 py-3">
        <span className="eyebrow mr-1">Ask about {s}</span>
        {actions.map(({ icon: Icon, label, prompt }) => (
          <button
            key={label}
            type="button"
            onClick={() => onAsk(prompt)}
            title={prompt}
            className="inline-flex items-center gap-1.5 rounded-lg border border-line bg-surface px-2.5 py-1.5 text-xs font-medium text-ink-2 transition-colors hover:border-accent hover:text-ink focus-visible:outline-2 focus-visible:outline-accent"
          >
            <Icon size={13} aria-hidden />
            {label}
          </button>
        ))}
      </div>
    </section>
  );
}
