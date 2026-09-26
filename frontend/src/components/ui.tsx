"use client";

import type { ReactNode } from "react";
import { TrendingDown, TrendingUp } from "lucide-react";
import { pct } from "@/lib/format";

/** Inline trend line for a list row. Decorative: the row's text carries the values. */
export function Sparkline({ values, width = 72, height = 26 }: { values: number[]; width?: number; height?: number }) {
  if (values.length < 2) return <svg width={width} height={height} aria-hidden />;
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = max - min || 1;
  const pts = values
    .map((v, i) => `${((i / (values.length - 1)) * (width - 2) + 1).toFixed(1)},${(height - 2 - ((v - min) / span) * (height - 4)).toFixed(1)}`)
    .join(" ");
  const last = pts.split(" ").pop()!.split(",");
  return (
    <svg width={width} height={height} aria-hidden className="shrink-0 overflow-visible">
      <polyline points={pts} fill="none" stroke="var(--series-1)" strokeWidth={1.5} strokeLinejoin="round" strokeLinecap="round" />
      <circle cx={last[0]} cy={last[1]} r={2} fill="var(--series-1)" />
    </svg>
  );
}

/** Signed % change with a direction icon, so direction never relies on colour alone. */
export function Change({ value, digits = 2, className = "" }: { value: number | null; digits?: number; className?: string }) {
  if (value === null || !Number.isFinite(value)) return <span className={`text-muted ${className}`}>–</span>;
  const up = value >= 0;
  const Icon = up ? TrendingUp : TrendingDown;
  return (
    <span className={`relative inline-flex items-center gap-1 tabular ${up ? "text-good-text" : "text-critical-text"} ${className}`}>
      <Icon size={13} strokeWidth={2.25} aria-hidden />
      <span className="sr-only">{up ? "up" : "down"}</span>
      {pct(value, digits, true)}
    </span>
  );
}

export function Segmented<T extends string>({
  options,
  value,
  onChange,
  label,
}: {
  options: { value: T; label: ReactNode; title?: string; disabled?: boolean }[];
  value: T;
  onChange: (value: T) => void;
  label: string;
}) {
  return (
    <div role="radiogroup" aria-label={label} className="inline-flex shrink-0 rounded-lg border border-line bg-surface-2 p-0.5">
      {options.map((o) => {
        const active = o.value === value;
        return (
          <button
            key={o.value}
            type="button"
            role="radio"
            aria-checked={active}
            title={o.title}
            disabled={o.disabled}
            onClick={() => onChange(o.value)}
            className={`inline-flex items-center gap-1.5 rounded-md px-2.5 py-1 text-xs font-medium transition-colors focus-visible:outline-2 focus-visible:outline-accent disabled:cursor-not-allowed disabled:opacity-50 ${
              active ? "bg-surface text-ink shadow-sm" : "text-ink-2 hover:text-ink"
            }`}
          >
            {o.label}
          </button>
        );
      })}
    </div>
  );
}

export function Chip({ children }: { children: ReactNode }) {
  return (
    <span className="inline-flex items-center rounded-md border border-line bg-surface-2 px-1.5 py-0.5 text-[11px] font-medium text-ink-2">
      {children}
    </span>
  );
}
