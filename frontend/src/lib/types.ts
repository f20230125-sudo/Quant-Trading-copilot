export type SymbolInfo = {
  symbol: string;
  name: string;
  category: string;
  tick_interval_s: number;
  decimals: number;
  description: string;
  design_vol: number | null;
  last_price: number;
};

export type Point = { t: number; v: number };

export type Engine = "local" | "claude";

export type SnapshotRow = {
  symbol: string;
  name: string;
  category: string;
  decimals: number;
  design_vol: number | null;
  last: number;
  change_pct: number;
  realized_vol: number;
  spark: number[];
};

export type Metrics = {
  total_return: number;
  sharpe: number;
  max_drawdown: number;
  bars: number;
};

export type StrategySpec = {
  signal:
    | { type: "sma_cross"; fast: number; slow: number }
    | { type: "rsi"; period: number; lower: number; upper: number; mode: "mean_reversion" | "momentum" }
    | { type: "breakout"; lookback: number };
  direction: "long_only" | "short_only" | "long_short";
  stop_loss_pct: number | null;
  take_profit_pct: number | null;
  fee_bps: number;
};

export type SymbolsUI = { kind: "symbols"; rows: SymbolInfo[] };

export type PricesUI = {
  kind: "prices";
  symbol: string;
  points: number;
  granularity_s: number;
  minutes: number;
  first: number;
  last: number;
  change_pct: number;
  high: number;
  low: number;
  series: Point[];
};

export type VolatilityUI = {
  kind: "volatility";
  symbol: string;
  design_vol: number | null;
  minutes: number;
  n_returns: number;
  window: number;
  realized_vol: number;
  current_rolling_vol: number;
  current_percentile: number;
  ewma_vol: number;
  garch: { forecast_vol: number; long_run_vol: number | null; persistence: number; horizon_periods: number } | null;
  jumps: { count: number; threshold_sigma: number; recent_epochs: number[] };
  largest_move: { epoch: number; log_return: number } | null;
  series: Point[];
};

export type Regime = "calm" | "normal" | "turbulent";

export type RegimeUI = {
  kind: "regime";
  symbol: string;
  window: number;
  minutes: number;
  median_vol: number;
  noise_band_pct: number;
  current_regime: Regime;
  current_vol: number;
  time_share: Record<Regime, number>;
  n_switches: number;
  segments: { label: Regime; start_epoch: number; end_epoch: number; bars: number; mean_vol: number }[];
  summary: string;
  series: Point[];
};

export type CompareUI = {
  kind: "compare";
  window: number;
  ticks_per_symbol: number;
  sorted_calmest_first: {
    symbol: string;
    design_vol: number | null;
    realized_vol: number;
    current_vol: number;
    current_percentile: number;
  }[];
};

export type BacktestUI = {
  kind: "backtest";
  symbol: string;
  granularity_s: number;
  minutes: number;
  bars: number;
  full: Metrics;
  in_sample: Metrics;
  out_of_sample: Metrics;
  n_trades: number;
  win_rate: number;
  avg_trade_return: number;
  exposure: number;
  buy_and_hold_return: number;
  null_test: { p_value: number; null_mean_return: number; null_p95_return: number; n_sims: number };
  fee_bps: number;
  verdict: string;
  strategy: StrategySpec;
  equity: Point[];
  buy_hold: Point[];
};

export type WalkForwardUI = {
  kind: "walk_forward";
  symbol: string;
  signal_type: string;
  bars: number;
  n_folds: number;
  grid_size: number;
  folds: {
    fold: number;
    chosen_params: Record<string, number | string>;
    in_sample_sharpe: number;
    out_of_sample_sharpe: number;
    out_of_sample_return: number;
  }[];
  mean_in_sample_sharpe: number;
  out_of_sample: Metrics;
  verdict: string;
  oos_equity: Point[];
};

export type ToolUI = SymbolsUI | PricesUI | VolatilityUI | RegimeUI | CompareUI | BacktestUI | WalkForwardUI;

export type Usage = {
  input_tokens: number;
  output_tokens: number;
  cache_read_input_tokens: number;
  requests: number;
};

export type AgentEvent =
  | { type: "text"; delta: string }
  | { type: "tool_start"; id: string; name: string }
  | {
      type: "tool_result";
      id: string;
      name: string;
      input: Record<string, unknown>;
      ok: boolean;
      error: string | null;
      ui: ToolUI | null;
    }
  | { type: "error"; message: string }
  | { type: "done"; usage: Usage | null; engine?: Engine };

export type TextPart = { kind: "text"; text: string };
export type ToolPart = {
  kind: "tool";
  id: string;
  name: string;
  status: "running" | "done" | "error";
  input?: Record<string, unknown>;
  ui?: ToolUI | null;
  error?: string | null;
};
export type ErrorPart = { kind: "error"; message: string };
export type Part = TextPart | ToolPart | ErrorPart;

export type ChatMessage =
  | { id: string; role: "user"; text: string }
  | { id: string; role: "assistant"; parts: Part[]; usage?: Usage | null; engine: Engine; streaming: boolean };
