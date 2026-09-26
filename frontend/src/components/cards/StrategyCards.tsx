import { LineChart } from "../charts/LineChart";
import { Metric, MetricGrid, Verdict, backtestTone, walkForwardTone } from "./primitives";
import { duration, num, pValue, pct } from "@/lib/format";
import type { BacktestUI, Metrics, WalkForwardUI } from "@/lib/types";

function SplitRow({ label, m }: { label: string; m: Metrics }) {
  return (
    <tr className="border-t border-grid">
      <td className="py-1 pr-3 text-ink-2">{label}</td>
      <td className="py-1 pr-3 text-right">{pct(m.total_return, 2, true)}</td>
      <td className="py-1 pr-3 text-right">{num(m.sharpe, 2)}</td>
      <td className="py-1 text-right">{pct(m.max_drawdown, 2)}</td>
    </tr>
  );
}

export function BacktestCard({ ui }: { ui: BacktestUI }) {
  // Equity is a growth multiple; show it as % return from the start.
  const toReturn = (points: { t: number; v: number }[]) => points.map((p) => ({ t: p.t, v: p.v - 1 }));
  return (
    <div className="space-y-2.5">
      <Verdict text={ui.verdict} tone={backtestTone(ui.verdict)} />
      <MetricGrid>
        <Metric label="Net return" value={pct(ui.full.total_return, 2, true)} />
        <Metric label="Buy & hold" value={pct(ui.buy_and_hold_return, 2, true)} />
        <Metric
          label="p-value (timing)"
          value={pValue(ui.null_test.p_value)}
          hint={`${ui.null_test.n_sims} circular-shift simulations; their 95th percentile return was ${pct(ui.null_test.null_p95_return, 2, true)}`}
        />
        <Metric label="Trades" value={ui.n_trades.toLocaleString()} />
        <Metric label="Win rate" value={pct(ui.win_rate, 1)} />
        <Metric label="Max drawdown" value={pct(ui.full.max_drawdown, 2)} />
      </MetricGrid>
      <LineChart
        series={[
          { id: "strategy", label: "Strategy (net of fees)", color: "var(--series-1)", points: toReturn(ui.equity) },
          { id: "bh", label: "Buy & hold", color: "var(--series-2)", points: toReturn(ui.buy_hold) },
        ]}
        yFormat={(v) => pct(v, 1, true)}
        refLine={{ value: 0 }}
        ariaLabel={`Cumulative return of the strategy versus buy and hold on ${ui.symbol}`}
        height={160}
      />
      <table className="w-full text-xs tabular">
        <thead className="text-muted">
          <tr>
            <th className="py-1 pr-3 text-left font-medium">Sample</th>
            <th className="py-1 pr-3 text-right font-medium">Return</th>
            <th className="py-1 pr-3 text-right font-medium">Sharpe (ann.)</th>
            <th className="py-1 text-right font-medium">Max DD</th>
          </tr>
        </thead>
        <tbody className="text-ink">
          <SplitRow label="In-sample (70%)" m={ui.in_sample} />
          <SplitRow label="Out-of-sample (30%)" m={ui.out_of_sample} />
        </tbody>
      </table>
      <p className="text-xs text-muted">
        {ui.bars.toLocaleString()} {ui.granularity_s ? `${ui.granularity_s}s candles` : "ticks"} over {duration(ui.minutes)} · fees{" "}
        {ui.fee_bps} bp per unit of turnover · exposure {pct(ui.exposure, 0)}
      </p>
    </div>
  );
}

function params(p: Record<string, number | string>) {
  return Object.entries(p)
    .filter(([k]) => k !== "mode")
    .map(([k, v]) => `${k} ${v}`)
    .join(", ");
}

export function WalkForwardCard({ ui }: { ui: WalkForwardUI }) {
  return (
    <div className="space-y-2.5">
      <Verdict text={ui.verdict} tone={walkForwardTone(ui.verdict)} />
      <MetricGrid>
        <Metric label="Mean in-sample Sharpe" value={num(ui.mean_in_sample_sharpe, 2)} />
        <Metric label="Out-of-sample Sharpe" value={num(ui.out_of_sample.sharpe, 2)} />
        <Metric label="Out-of-sample return" value={pct(ui.out_of_sample.total_return, 2, true)} />
      </MetricGrid>
      <div className="overflow-x-auto">
        <table className="w-full text-xs tabular">
          <thead className="text-muted">
            <tr>
              <th className="py-1 pr-3 text-left font-medium">Fold</th>
              <th className="py-1 pr-3 text-left font-medium">Chosen on train</th>
              <th className="py-1 pr-3 text-right font-medium">IS Sharpe</th>
              <th className="py-1 pr-3 text-right font-medium">OOS Sharpe</th>
              <th className="py-1 text-right font-medium">OOS return</th>
            </tr>
          </thead>
          <tbody className="text-ink">
            {ui.folds.map((f) => (
              <tr key={f.fold} className="border-t border-grid">
                <td className="py-1 pr-3 text-ink-2">{f.fold}</td>
                <td className="py-1 pr-3 whitespace-nowrap">{params(f.chosen_params)}</td>
                <td className="py-1 pr-3 text-right">{num(f.in_sample_sharpe, 2)}</td>
                <td className="py-1 pr-3 text-right">{num(f.out_of_sample_sharpe, 2)}</td>
                <td className="py-1 text-right">{pct(f.out_of_sample_return, 2, true)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <LineChart
        series={[
          {
            id: "oos",
            label: "Stitched out-of-sample return",
            color: "var(--series-1)",
            points: ui.oos_equity.map((p) => ({ t: p.t, v: p.v - 1 })),
          },
        ]}
        yFormat={(v) => pct(v, 1, true)}
        refLine={{ value: 0 }}
        ariaLabel={`Stitched out-of-sample return of the walk-forward on ${ui.symbol}`}
        height={130}
      />
      <p className="text-xs text-muted">
        {ui.grid_size} parameter sets searched per fold · {ui.n_folds} folds · {ui.bars.toLocaleString()} bars
      </p>
    </div>
  );
}
