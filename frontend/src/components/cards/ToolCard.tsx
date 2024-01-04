import { ChevronRight, FlaskConical, Layers, List, ListOrdered, LoaderCircle, Route, TrendingUp, TriangleAlert, Waves } from "lucide-react";
import { CompareCard, PricesCard, RegimeCard, SymbolsCard, VolatilityCard } from "./MarketCards";
import { BacktestCard, WalkForwardCard } from "./StrategyCards";
import { SymbolButton } from "./primitives";
import { strategyLabel } from "@/lib/format";
import type { ToolPart, ToolUI } from "@/lib/types";

const TOOLS: Record<string, { title: string; icon: typeof Waves }> = {
  list_symbols: { title: "Market catalog", icon: List },
  get_price_summary: { title: "Price summary", icon: TrendingUp },
  volatility_report: { title: "Volatility report", icon: Waves },
  detect_regime: { title: "Regime detection", icon: Layers },
  compare_volatility: { title: "Volatility ranking", icon: ListOrdered },
  run_backtest: { title: "Backtest", icon: FlaskConical },
  walk_forward_optimize: { title: "Walk-forward optimisation", icon: Route },
};

function Body({ ui, onSymbol }: { ui: ToolUI; onSymbol?: (s: string) => void }) {
  switch (ui.kind) {
    case "symbols":
      return <SymbolsCard ui={ui} onSymbol={onSymbol} />;
    case "prices":
      return <PricesCard ui={ui} />;
    case "volatility":
      return <VolatilityCard ui={ui} />;
    case "regime":
      return <RegimeCard ui={ui} />;
    case "compare":
      return <CompareCard ui={ui} onSymbol={onSymbol} />;
    case "backtest":
      return <BacktestCard ui={ui} />;
    case "walk_forward":
      return <WalkForwardCard ui={ui} />;
  }
}

export function ToolCard({ part, onSymbol }: { part: ToolPart; onSymbol?: (s: string) => void }) {
  const input = part.input ?? {};
  const symbol = typeof input.symbol === "string" ? input.symbol.toUpperCase() : null;
  const strategy = input.strategy as Parameters<typeof strategyLabel>[0] | undefined;
  const subtitle = strategy?.signal ? strategyLabel(strategy) : null;
  const tool = TOOLS[part.name] ?? { title: part.name, icon: Waves };
  const Icon = tool.icon;

  return (
    <details open className="group overflow-hidden rounded-xl border border-line bg-surface">
      <summary className="flex cursor-pointer list-none items-center gap-2 bg-surface-2/60 px-3 py-2 text-sm [&::-webkit-details-marker]:hidden">
        <ChevronRight
          size={14}
          className="shrink-0 text-muted transition-transform group-open:rotate-90 motion-reduce:transition-none"
          aria-hidden
        />
        <Icon size={14} className="shrink-0 text-accent" aria-hidden />
        <span className="shrink-0 font-medium text-ink">{tool.title}</span>
        {symbol && (
          <span className="shrink-0 text-xs">
            <SymbolButton symbol={symbol} onClick={onSymbol} />
          </span>
        )}
        {subtitle && <span className="min-w-0 truncate text-xs text-ink-2">{subtitle}</span>}
        <span className="ml-auto shrink-0 text-xs text-muted">
          {part.status === "running" && (
            <span className="inline-flex items-center gap-1.5">
              <LoaderCircle size={13} className="animate-spin text-accent motion-reduce:animate-none" aria-hidden />
              Running
            </span>
          )}
          {part.status === "error" && (
            <span className="inline-flex items-center gap-1 text-critical-text">
              <TriangleAlert size={13} aria-hidden /> Failed
            </span>
          )}
        </span>
      </summary>
      <div className="border-t border-line px-3 py-3">
        {part.status === "running" && <div className="h-16 animate-pulse rounded-lg bg-surface-2 motion-reduce:animate-none" />}
        {part.status === "error" && (
          <p className="text-sm text-ink-2">
            <span className="font-medium text-critical-text">Tool error:</span> {part.error}
            <span className="block text-xs text-muted">The copilot sees this error and can correct its request.</span>
          </p>
        )}
        {part.status === "done" && part.ui && <Body ui={part.ui} onSymbol={onSymbol} />}
      </div>
    </details>
  );
}
