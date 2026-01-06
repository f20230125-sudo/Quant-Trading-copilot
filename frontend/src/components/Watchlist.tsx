"use client";

import { useState } from "react";
import { Search } from "lucide-react";
import { Change, Sparkline } from "./ui";
import { price } from "@/lib/format";
import type { SnapshotRow } from "@/lib/types";

const GROUPS: [string, string][] = [
  ["volatility", "Volatility"],
  ["jump", "Jump"],
  ["crash_boom", "Crash / Boom"],
  ["step", "Step"],
  ["regime", "Regime"],
  ["momentum", "Momentum"],
];

type Props = {
  rows: SnapshotRow[] | null;
  selected: string;
  onSelect: (symbol: string) => void;
  windowMinutes: number;
};

/** Full watchlist for wide screens: search, grouped rows, sparklines. */
export function WatchlistRail({ rows, selected, onSelect, windowMinutes }: Props) {
  const [query, setQuery] = useState("");
  const q = query.trim().toLowerCase();
  const visible = (rows ?? []).filter((r) => !q || r.symbol.toLowerCase().includes(q) || r.name.toLowerCase().includes(q));

  return (
    <nav className="panel flex min-h-0 flex-col" aria-label="Markets">
      <div className="flex items-center justify-between px-4 pt-4">
        <h2 className="eyebrow">Markets</h2>
        <span className="text-[11px] text-muted">{windowMinutes}m change</span>
      </div>
      <div className="px-3 pb-2 pt-3">
        <label className="flex items-center gap-2 rounded-lg border border-line bg-surface-2 px-2.5 py-1.5 focus-within:border-accent">
          <Search size={14} className="text-muted" aria-hidden />
          <span className="sr-only">Filter markets</span>
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Filter"
            className="w-full bg-transparent text-sm text-ink placeholder:text-muted focus:outline-none"
          />
        </label>
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto px-2 pb-3">
        {rows === null &&
          Array.from({ length: 8 }, (_, i) => <div key={i} className="mx-1 my-1.5 h-11 animate-pulse rounded-lg bg-surface-2" />)}
        {GROUPS.map(([category, label]) => {
          const group = visible.filter((r) => r.category === category);
          if (!group.length) return null;
          return (
            <div key={category} className="mt-2">
              <div className="px-2 pb-1 text-[11px] font-medium text-muted">{label}</div>
              <ul>
                {group.map((r) => {
                  const active = r.symbol === selected;
                  return (
                    <li key={r.symbol}>
                      <button
                        type="button"
                        onClick={() => onSelect(r.symbol)}
                        aria-current={active ? "true" : undefined}
                        className={`group relative grid w-full grid-cols-[1fr_auto_auto] items-center gap-2.5 rounded-lg px-2 py-1.5 text-left transition-colors focus-visible:outline-2 focus-visible:outline-accent ${
                          active ? "bg-accent-soft" : "hover:bg-surface-2"
                        }`}
                      >
                        {active && <span className="absolute inset-y-2 left-0 w-0.5 rounded-full bg-accent" aria-hidden />}
                        <span className="min-w-0">
                          <span className="block truncate text-[13px] font-semibold text-ink">{r.symbol}</span>
                          <span className="block truncate text-[11px] text-muted">{r.name.replace(" Index", "")}</span>
                        </span>
                        <Sparkline values={r.spark} width={56} height={24} />
                        <span className="text-right">
                          <span className="block text-[13px] font-medium text-ink tabular">{price(r.last, r.decimals)}</span>
                          <Change value={r.change_pct} className="text-[11px]" />
                        </span>
                      </button>
                    </li>
                  );
                })}
              </ul>
            </div>
          );
        })}
        {rows !== null && visible.length === 0 && <p className="px-2 py-4 text-sm text-muted">No markets match “{query}”.</p>}
      </div>
    </nav>
  );
}

/** Compact, horizontally scrolling watchlist for narrower screens. */
export function WatchlistStrip({ rows, selected, onSelect }: Props) {
  return (
    <nav aria-label="Markets" className="relative -mx-1 overflow-x-auto px-1 pb-1">
      <ul className="flex gap-2">
        {(rows ?? []).map((r) => {
          const active = r.symbol === selected;
          return (
            <li key={r.symbol}>
              <button
                type="button"
                onClick={() => onSelect(r.symbol)}
                aria-current={active ? "true" : undefined}
                className={`flex items-center gap-2 whitespace-nowrap rounded-lg border px-2.5 py-1.5 text-left transition-colors focus-visible:outline-2 focus-visible:outline-accent ${
                  active ? "border-accent bg-accent-soft" : "border-line bg-surface hover:bg-surface-2"
                }`}
              >
                <span className="text-xs font-semibold text-ink">{r.symbol}</span>
                <Change value={r.change_pct} className="text-[11px]" />
              </button>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}
