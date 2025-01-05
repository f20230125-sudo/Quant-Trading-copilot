import { LineChart } from "../charts/LineChart";
import { Metric, MetricGrid, SymbolButton } from "./primitives";
import { clock, duration, num, pct, vol } from "@/lib/format";
import type { CompareUI, PricesUI, Regime, RegimeUI, SymbolsUI, VolatilityUI } from "@/lib/types";

type OnSymbol = (symbol: string) => void;

export function SymbolsCard({ ui, onSymbol }: { ui: SymbolsUI; onSymbol?: OnSymbol }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-xs tabular">
        <thead className="text-left text-muted">
          <tr>
            <th className="py-1 pr-3 font-medium">Symbol</th>
            <th className="py-1 pr-3 font-medium">Category</th>
            <th className="py-1 pr-3 text-right font-medium">Tick</th>
            <th className="py-1 text-right font-medium">Design vol</th>
          </tr>
        </thead>
        <tbody>
          {ui.rows.map((r) => (
            <tr key={r.symbol} className="border-t border-grid">
              <td className="py-1 pr-3">
                <SymbolButton symbol={r.symbol} onClick={onSymbol} />
              </td>
              <td className="py-1 pr-3 text-ink-2">{r.category.replace("_", " / ")}</td>
              <td className="py-1 pr-3 text-right text-ink-2">{r.tick_interval_s}s</td>
              <td className="py-1 text-right text-ink-2">{r.design_vol ? vol(r.design_vol) : "–"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function PricesCard({ ui }: { ui: PricesUI }) {
  const digits = Math.abs(ui.last) >= 1000 ? 2 : 4;
  return (
    <div className="space-y-2">
      <MetricGrid>
        <Metric label="Change" value={pct(ui.change_pct / 100, 3, true)} />
        <Metric label="High" value={num(ui.high, digits)} />
        <Metric label="Low" value={num(ui.low, digits)} />
      </MetricGrid>
      <LineChart
        series={[{ id: "price", label: "Price", color: "var(--series-1)", points: ui.series, area: true }]}
        yFormat={(v) => num(v, digits)}
        tickFormat={(v) => num(v, ui.high - ui.low > 20 ? 0 : digits)}
        ariaLabel={`${ui.symbol} price over ${duration(ui.minutes)}`}
        height={140}
      />
      <p className="text-xs text-muted">
        {ui.points.toLocaleString()} {ui.granularity_s ? `${ui.granularity_s}s candles` : "ticks"} over {duration(ui.minutes)}
      </p>
    </div>
  );
}

export function VolatilityCard({ ui }: { ui: VolatilityUI }) {
  return (
    <div className="space-y-2.5">
      <MetricGrid>
        <Metric label="Realized (full sample)" value={vol(ui.realized_vol)} />
        <Metric label={`Current (${ui.window}-tick)`} value={vol(ui.current_rolling_vol)} />
        <Metric label="Design" value={ui.design_vol ? vol(ui.design_vol) : "n/a"} />
        <Metric label="EWMA (λ 0.94)" value={vol(ui.ewma_vol)} />
        <Metric
          label="GARCH forecast"
          value={ui.garch ? vol(ui.garch.forecast_vol) : "n/a"}
          hint={ui.garch ? `Average over the next ${ui.garch.horizon_periods} ticks; persistence ${num(ui.garch.persistence, 3)}` : "Fit failed"}
        />
        <Metric label="Jumps (> 6σ)" value={ui.jumps.count} />
      </MetricGrid>
      <div>
        <div className="mb-1 flex justify-between text-xs text-muted">
          <span>Current vol vs this sample</span>
          <span className="tabular text-ink-2">{num(ui.current_percentile, 0)}th percentile</span>
        </div>
        <div className="h-1.5 w-full rounded-full bg-surface-2" role="meter" aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(ui.current_percentile)} aria-label="Current volatility percentile">
          <div className="h-full rounded-full bg-accent" style={{ width: `${Math.max(2, ui.current_percentile)}%` }} />
        </div>
      </div>
      <LineChart
        series={[{ id: "vol", label: "Rolling volatility", color: "var(--series-1)", points: ui.series }]}
        yFormat={(v) => vol(v)}
        refLine={ui.design_vol ? { value: ui.design_vol, label: `design ${vol(ui.design_vol)}` } : undefined}
        ariaLabel={`${ui.symbol} ${ui.window}-tick rolling annualised volatility`}
        height={140}
      />
      {ui.largest_move && (
        <p className="text-xs text-muted">
          Largest single move: <span className="tabular text-ink-2">{pct(ui.largest_move.log_return, 3, true)}</span> at{" "}
          {clock(ui.largest_move.epoch, true)} · {ui.n_returns.toLocaleString()} ticks over {duration(ui.minutes)}
        </p>
      )}
    </div>
  );
}

const REGIME_COLOR: Record<Regime, string> = {
  calm: "var(--regime-calm)",
  normal: "var(--regime-normal)",
  turbulent: "var(--regime-turbulent)",
};

export function RegimeCard({ ui }: { ui: RegimeUI }) {
  const order: Regime[] = ["calm", "normal", "turbulent"];
  return (
    <div className="space-y-2.5">
      <MetricGrid>
        <Metric
          label="Current regime"
          value={
            <span className="inline-flex items-center gap-1.5 capitalize">
              <span className="h-2.5 w-2.5 rounded-sm" style={{ background: REGIME_COLOR[ui.current_regime] }} aria-hidden />
              {ui.current_regime}
            </span>
          }
        />
        <Metric label="Current vol" value={vol(ui.current_vol)} />
        <Metric label="Regime switches" value={ui.n_switches} hint={`Noise band ±${num(ui.noise_band_pct, 1)}% around median`} />
      </MetricGrid>
      <div>
        <div className="flex h-3 w-full gap-[2px] overflow-hidden rounded" aria-hidden>
          {order.map((r) =>
            ui.time_share[r] > 0 ? (
              <div key={r} style={{ width: `${ui.time_share[r] * 100}%`, background: REGIME_COLOR[r] }} />
            ) : null,
          )}
        </div>
        <ul className="mt-1.5 flex flex-wrap gap-x-4 gap-y-1 text-xs text-ink-2">
          {order.map((r) => (
            <li key={r} className="flex items-center gap-1.5 capitalize">
              <span className="h-2.5 w-2.5 rounded-sm" style={{ background: REGIME_COLOR[r] }} aria-hidden />
              {r} <span className="tabular text-muted">{pct(ui.time_share[r], 0)}</span>
            </li>
          ))}
        </ul>
      </div>
      <LineChart
        series={[{ id: "vol", label: "Rolling volatility", color: "var(--ink-2)", points: ui.series }]}
        yFormat={(v) => vol(v)}
        bands={ui.segments
          .filter((s) => s.label !== "normal")
          .map((s) => ({ start: s.start_epoch, end: s.end_epoch, color: REGIME_COLOR[s.label], label: s.label }))}
        refLine={{ value: ui.median_vol, label: `median ${vol(ui.median_vol)}` }}
        ariaLabel={`${ui.symbol} rolling volatility with calm and turbulent periods shaded`}
        height={140}
      />
      <p className="text-xs text-ink-2">{ui.summary}</p>
    </div>
  );
}

export function CompareCard({ ui, onSymbol }: { ui: CompareUI; onSymbol?: OnSymbol }) {
  const max = Math.max(...ui.sorted_calmest_first.map((r) => r.current_vol));
  return (
    <div>
      <p className="mb-2 text-xs text-muted">
        Current {ui.window}-tick annualised volatility, calmest first. Tick marks show design volatility.
      </p>
      <ul className="space-y-1.5">
        {ui.sorted_calmest_first.map((r) => (
          <li key={r.symbol} className="grid grid-cols-[88px_1fr_52px] items-center gap-2 text-xs">
            <SymbolButton symbol={r.symbol} onClick={onSymbol} />
            <div className="relative h-3" title={`Current ${vol(r.current_vol)} · realized ${vol(r.realized_vol)}`}>
              <div
                className="h-full rounded-r-[4px] bg-accent"
                style={{ width: `${Math.max(1, (r.current_vol / max) * 100)}%` }}
              />
              {r.design_vol !== null && (
                <div
                  className="absolute -top-0.5 h-4 w-[2px] rounded bg-ink"
                  style={{ left: `${Math.min(100, (r.design_vol / max) * 100)}%` }}
                  aria-hidden
                />
              )}
            </div>
            <span className="text-right tabular text-ink">{vol(r.current_vol)}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}
