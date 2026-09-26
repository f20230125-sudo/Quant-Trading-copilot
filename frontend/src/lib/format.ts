const isNum = (v: unknown): v is number => typeof v === "number" && Number.isFinite(v);

/** 0.0123 -> "1.23%" */
export function pct(v: number | null | undefined, digits = 2, signed = false): string {
  if (!isNum(v)) return "–";
  const s = (v * 100).toFixed(digits);
  return `${signed && v > 0 ? "+" : ""}${s}%`;
}

/** Annualised volatility decimal -> "74.6%" */
export const vol = (v: number | null | undefined) => pct(v, 1);

export function num(v: number | null | undefined, digits = 2): string {
  if (!isNum(v)) return "–";
  return v.toLocaleString("en-US", { minimumFractionDigits: digits, maximumFractionDigits: digits });
}

export function price(v: number | null | undefined, decimals = 2): string {
  return num(v, decimals);
}

/** Compact integer: 12,000 -> "12K" */
export function compact(v: number | null | undefined): string {
  if (!isNum(v)) return "–";
  return Intl.NumberFormat("en-US", { notation: "compact", maximumFractionDigits: 1 }).format(v);
}

export function pValue(p: number | null | undefined): string {
  if (!isNum(p)) return "–";
  return p < 0.001 ? "< 0.001" : p.toFixed(3);
}

export function clock(epoch: number, seconds = false): string {
  return new Date(epoch * 1000).toLocaleTimeString([], {
    hour: "2-digit",
    minute: "2-digit",
    ...(seconds ? { second: "2-digit" } : {}),
  });
}

export function duration(minutes: number | null | undefined): string {
  if (!isNum(minutes)) return "–";
  if (minutes < 90) return `${Math.round(minutes)} min`;
  const hours = minutes / 60;
  return hours < 48 ? `${hours.toFixed(1)} h` : `${(hours / 24).toFixed(1)} days`;
}

/** Short human label for a strategy spec. */
export function strategyLabel(s: {
  signal: { type: string; [k: string]: unknown };
  direction?: string;
  stop_loss_pct?: number | null;
  take_profit_pct?: number | null;
}): string {
  const sig = s.signal;
  let label: string;
  if (sig.type === "sma_cross") label = `SMA ${sig.fast}/${sig.slow} cross`;
  else if (sig.type === "rsi")
    label = `RSI(${sig.period ?? 14}) ${sig.mode === "momentum" ? "momentum" : "mean-reversion"} ${sig.lower ?? 30}/${sig.upper ?? 70}`;
  else if (sig.type === "breakout") label = `${sig.lookback}-bar breakout`;
  else label = sig.type;
  const parts = [label];
  if (s.direction && s.direction !== "long_short") parts.push(s.direction === "long_only" ? "long only" : "short only");
  if (s.stop_loss_pct) parts.push(`SL ${s.stop_loss_pct}%`);
  if (s.take_profit_pct) parts.push(`TP ${s.take_profit_pct}%`);
  return parts.join(" · ");
}
