"use client";

import { useMemo, useState } from "react";
import { useElementWidth } from "@/lib/hooks";
import { clock } from "@/lib/format";
import type { Point } from "@/lib/types";

export type ChartSeries = {
  id: string;
  label: string;
  /** A CSS colour, normally a token such as var(--series-1). */
  color: string;
  points: Point[];
  area?: boolean;
};

type Band = { start: number; end: number; color: string; label: string };

type Props = {
  series: ChartSeries[];
  /** Formats values in the tooltip (and axis ticks unless tickFormat is given). */
  yFormat: (v: number) => string;
  tickFormat?: (v: number) => string;
  ariaLabel: string;
  height?: number;
  refLine?: { value: number; label?: string };
  bands?: Band[];
  compact?: boolean;
};

const CHAR_PX = 6.6; // approximate width of an 11px system-ui digit

function niceTicks(min: number, max: number, count = 4): number[] {
  const span = max - min || Math.abs(max) || 1;
  const raw = span / count;
  const mag = 10 ** Math.floor(Math.log10(raw));
  const err = raw / mag;
  const step = (err >= 7.5 ? 10 : err >= 3.5 ? 5 : err >= 1.5 ? 2 : 1) * mag;
  const ticks: number[] = [];
  for (let v = Math.ceil(min / step) * step; v <= max + step * 1e-9; v += step) ticks.push(Number(v.toPrecision(12)));
  return ticks;
}

function nearest(points: Point[], t: number): Point | undefined {
  let lo = 0;
  let hi = points.length - 1;
  if (hi < 0) return undefined;
  while (hi - lo > 1) {
    const mid = (lo + hi) >> 1;
    if (points[mid].t < t) lo = mid;
    else hi = mid;
  }
  return Math.abs(points[lo].t - t) <= Math.abs(points[hi].t - t) ? points[lo] : points[hi];
}

export function LineChart({ series, yFormat, tickFormat, ariaLabel, height = 160, refLine, bands, compact = false }: Props) {
  const [ref, width] = useElementWidth<HTMLDivElement>();
  const [hoverT, setHoverT] = useState<number | null>(null);
  const tickFmt = tickFormat ?? yFormat;

  const geo = useMemo(() => {
    const all = series.flatMap((s) => s.points);
    if (!all.length || width === 0) return null;
    const t0 = Math.min(...all.map((p) => p.t));
    const t1 = Math.max(...all.map((p) => p.t));
    let y0 = Math.min(...all.map((p) => p.v), refLine?.value ?? Infinity);
    let y1 = Math.max(...all.map((p) => p.v), refLine?.value ?? -Infinity);
    const pad = (y1 - y0 || Math.abs(y1) || 1) * 0.08;
    y0 -= pad;
    y1 += pad;
    const ticks = compact ? [] : niceTicks(y0, y1);
    // Size the y-axis gutter to the widest tick label so labels never clip.
    const gutter = compact ? 6 : Math.ceil(Math.max(3, ...ticks.map((t) => tickFmt(t).length)) * CHAR_PX) + 14;
    const m = compact ? { top: 6, right: 6, bottom: 6, left: 6 } : { top: 8, right: 8, bottom: 20, left: gutter };
    const iw = Math.max(1, width - m.left - m.right);
    const ih = height - m.top - m.bottom;
    const x = (t: number) => m.left + ((t - t0) / (t1 - t0 || 1)) * iw;
    const y = (v: number) => m.top + (1 - (v - y0) / (y1 - y0)) * ih;
    const invX = (px: number) => t0 + ((px - m.left) / iw) * (t1 - t0);
    return { t0, t1, x, y, invX, iw, ih, ticks, m };
  }, [series, width, height, refLine, compact, tickFmt]);
  const m = geo?.m ?? { top: 0, right: 0, bottom: 0, left: 0 };

  const hovered =
    geo && hoverT !== null
      ? series.map((s) => ({ s, p: nearest(s.points, hoverT) })).filter((h): h is { s: ChartSeries; p: Point } => !!h.p)
      : [];
  const anchorT = hovered[0]?.p.t;
  const tooltipLeft = geo && anchorT !== undefined ? geo.x(anchorT) : 0;
  const flip = tooltipLeft > width * 0.6;

  return (
    <div className="relative w-full">
      {(series.length > 1 || refLine?.label) && (
        <ul className="mb-1.5 flex flex-wrap gap-x-4 gap-y-1 text-xs text-ink-2" aria-hidden>
          {series.length > 1 &&
            series.map((s) => (
              <li key={s.id} className="flex items-center gap-1.5">
                <span className="inline-block h-0.5 w-3.5 rounded-full" style={{ background: s.color }} />
                {s.label}
              </li>
            ))}
          {refLine?.label && (
            <li className="flex items-center gap-1.5">
              <span className="inline-block h-0.5 w-3.5 rounded-full bg-axis" />
              {refLine.label}
            </li>
          )}
        </ul>
      )}
      <div ref={ref} className="relative" style={{ height }}>
        {geo && (
          <svg
            width={width}
            height={height}
            role="img"
            aria-label={ariaLabel}
            className="block touch-none select-none"
            onPointerMove={(e) => {
              const rect = e.currentTarget.getBoundingClientRect();
              const t = geo.invX(e.clientX - rect.left);
              setHoverT(Math.min(geo.t1, Math.max(geo.t0, t)));
            }}
            onPointerLeave={() => setHoverT(null)}
          >
            {bands?.map((b, i) => (
              <rect
                key={i}
                x={geo.x(b.start)}
                y={m.top}
                width={Math.max(1, geo.x(b.end) - geo.x(b.start))}
                height={geo.ih}
                fill={b.color}
                opacity={0.14}
              />
            ))}
            {geo.ticks.map((v) => (
              <g key={v}>
                <line x1={m.left} x2={width - m.right} y1={geo.y(v)} y2={geo.y(v)} stroke="var(--grid)" strokeWidth={1} />
                <text x={m.left - 8} y={geo.y(v)} dy="0.32em" textAnchor="end" fontSize={11} fill="var(--muted)" className="tabular">
                  {tickFmt(v)}
                </text>
              </g>
            ))}
            {refLine && (
              <g>
                <line
                  x1={m.left}
                  x2={width - m.right}
                  y1={geo.y(refLine.value)}
                  y2={geo.y(refLine.value)}
                  stroke="var(--axis)"
                  strokeWidth={1.5}
                />
              </g>
            )}
            {series.map((s) => {
              if (!s.points.length) return null;
              const line = s.points.map((p, i) => `${i ? "L" : "M"}${geo.x(p.t).toFixed(1)},${geo.y(p.v).toFixed(1)}`).join("");
              const base = m.top + geo.ih;
              const first = s.points[0];
              const last = s.points[s.points.length - 1];
              return (
                <g key={s.id}>
                  {s.area && (
                    <path
                      d={`${line}L${geo.x(last.t).toFixed(1)},${base}L${geo.x(first.t).toFixed(1)},${base}Z`}
                      fill={s.color}
                      opacity={0.1}
                    />
                  )}
                  <path d={line} fill="none" stroke={s.color} strokeWidth={2} strokeLinejoin="round" strokeLinecap="round" />
                </g>
              );
            })}
            {!compact && (
              <>
                <text x={m.left} y={height - 4} fontSize={11} fill="var(--muted)">
                  {clock(geo.t0)}
                </text>
                <text x={width - m.right} y={height - 4} fontSize={11} fill="var(--muted)" textAnchor="end">
                  {clock(geo.t1)}
                </text>
              </>
            )}
            {anchorT !== undefined && (
              <g pointerEvents="none">
                <line x1={geo.x(anchorT)} x2={geo.x(anchorT)} y1={m.top} y2={m.top + geo.ih} stroke="var(--axis)" strokeWidth={1} />
                {hovered.map(({ s, p }) => (
                  <circle key={s.id} cx={geo.x(p.t)} cy={geo.y(p.v)} r={4} fill={s.color} stroke="var(--surface)" strokeWidth={2} />
                ))}
              </g>
            )}
          </svg>
        )}
        {geo && anchorT !== undefined && (
          <div
            className="pointer-events-none absolute top-1 z-10 rounded-md border border-line bg-surface px-2 py-1.5 text-xs shadow-sm"
            style={flip ? { right: width - tooltipLeft + 10 } : { left: tooltipLeft + 10 }}
          >
            <div className="mb-0.5 text-muted tabular">{clock(anchorT, true)}</div>
            {hovered.map(({ s, p }) => (
              <div key={s.id} className="flex items-center gap-1.5 whitespace-nowrap text-ink">
                <span className="inline-block h-2 w-2 rounded-full" style={{ background: s.color }} />
                {series.length > 1 && <span className="text-ink-2">{s.label}</span>}
                <span className="tabular font-medium">{yFormat(p.v)}</span>
              </div>
            ))}
          </div>
        )}
      </div>
      {/* Tables ignore height: 1px, so the sr-only clip goes on a wrapper div. */}
      <div className="sr-only">
      <table>
        <caption>{ariaLabel}</caption>
        <thead>
          <tr>
            <th>Time</th>
            {series.map((s) => (
              <th key={s.id}>{s.label}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {(series[0]?.points ?? []).map((p, i) => (
            <tr key={p.t}>
              <td>{clock(p.t, true)}</td>
              {series.map((s) => (
                <td key={s.id}>{s.points[i] ? yFormat(s.points[i].v) : ""}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
      </div>
    </div>
  );
}
