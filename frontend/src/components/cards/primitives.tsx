import type { ReactNode } from "react";

export function Metric({ label, value, hint }: { label: string; value: ReactNode; hint?: string }) {
  return (
    <div className="min-w-0 rounded-lg bg-surface-2 px-2.5 py-2" title={hint}>
      <div className="truncate text-[11px] text-muted">{label}</div>
      <div className="truncate text-sm font-semibold text-ink">{value}</div>
    </div>
  );
}

export function MetricGrid({ children }: { children: ReactNode }) {
  return <div className="grid grid-cols-2 gap-1.5 sm:grid-cols-3">{children}</div>;
}

type Tone = "good" | "warning" | "neutral";

const TONES: Record<Tone, { icon: string; label: string; bar: string }> = {
  good: { icon: "✓", label: "Evidence of edge", bar: "var(--good)" },
  warning: { icon: "!", label: "Caution", bar: "var(--warning)" },
  neutral: { icon: "○", label: "No edge", bar: "var(--axis)" },
};

/** A verdict callout. Status colour always comes with an icon and a label, never alone. */
export function Verdict({ text, tone }: { text: string; tone: Tone }) {
  const t = TONES[tone];
  return (
    <div className="flex gap-2.5 rounded-lg border border-line bg-surface-2 p-2.5 text-sm">
      <span className="w-1 shrink-0 rounded-full" style={{ background: t.bar }} aria-hidden />
      <div>
        <div className="mb-0.5 flex items-center gap-1.5 text-xs font-semibold text-ink">
          <span
            className="grid h-4 w-4 place-items-center rounded-full text-[10px] text-white"
            style={{ background: t.bar === "var(--axis)" ? "var(--muted)" : t.bar }}
            aria-hidden
          >
            {t.icon}
          </span>
          {t.label}
        </div>
        <p className="text-ink-2">{text}</p>
      </div>
    </div>
  );
}

export function backtestTone(verdict: string): Tone {
  if (verdict.startsWith("Possible edge")) return "good";
  if (verdict.startsWith("The entry timing")) return "warning";
  return "neutral";
}

export function walkForwardTone(verdict: string): Tone {
  if (verdict.includes("fitting noise")) return "warning";
  if (verdict.includes("retained")) return "good";
  return "neutral";
}

export function SymbolButton({ symbol, onClick }: { symbol: string; onClick?: (s: string) => void }) {
  if (!onClick) return <span className="font-semibold">{symbol}</span>;
  return (
    <button
      type="button"
      onClick={() => onClick(symbol)}
      className="rounded font-semibold text-accent underline-offset-2 hover:underline focus:outline-2 focus:outline-accent"
      title={`Show ${symbol} on the chart`}
    >
      {symbol}
    </button>
  );
}
