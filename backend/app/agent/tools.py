"""Tools the copilot can call.

Each tool has a pydantic input model (its JSON schema is what Claude sees, and
the same model validates what Claude sends back) and a handler that returns two
views of the result: a compact JSON payload for the model, and a richer payload
(with chart series) that the frontend renders as a card.

Market data is snapshotted on the event loop, where the simulator's clock
runs; the number crunching then happens in a worker thread so a slow backtest
never stalls the live tick stream.
"""

from __future__ import annotations

import asyncio
import json
import math
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

import numpy as np
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from ..market import SyntheticMarket, UnknownSymbolError
from ..quant.backtest import run_backtest, walk_forward
from ..quant.regime import detect_regimes
from ..quant.series import downsample
from ..quant.strategies import StrategySpec
from ..quant.volatility import log_returns, periods_per_year, realized_vol, rolling_vol, volatility_report

MAX_TICKS = 20_000
SYMBOL_DESC = "Index symbol, e.g. VOL75. Call list_symbols if unsure which symbols exist."
GRANULARITY_DESC = (
    "0 analyses raw ticks. A positive value aggregates ticks into candles of that many "
    "seconds (e.g. 60) and uses candle closes, which covers a longer time span."
)


# --------------------------------------------------------------------------- inputs

class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ListSymbolsInput(_Input):
    pass


class PriceSummaryInput(_Input):
    symbol: str = Field(description=SYMBOL_DESC)
    count: int = Field(500, ge=10, le=MAX_TICKS, description="Number of most recent ticks or candles.")
    granularity_s: int = Field(0, ge=0, le=86_400, description=GRANULARITY_DESC)


class VolatilityInput(_Input):
    symbol: str = Field(description=SYMBOL_DESC)
    count: int = Field(5000, ge=200, le=MAX_TICKS, description="Number of most recent ticks to analyse.")
    window: int = Field(100, ge=10, le=2000, description="Rolling window, in ticks, for current volatility.")


class RegimeInput(_Input):
    symbol: str = Field(description=SYMBOL_DESC)
    count: int = Field(10_000, ge=500, le=MAX_TICKS, description="Number of most recent ticks to analyse.")
    window: int = Field(100, ge=20, le=2000, description="Rolling volatility window, in ticks.")


class CompareInput(_Input):
    symbols: list[str] | None = Field(
        None, max_length=12, description="Symbols to compare. Omit to compare every index."
    )
    count: int = Field(2000, ge=200, le=MAX_TICKS, description="Ticks of history per symbol.")
    window: int = Field(100, ge=10, le=2000, description="Rolling window, in ticks, for current volatility.")


class BacktestInput(_Input):
    symbol: str = Field(description=SYMBOL_DESC)
    strategy: StrategySpec
    count: int = Field(10_000, ge=200, le=MAX_TICKS, description="Number of most recent ticks or candles to test on.")
    granularity_s: int = Field(0, ge=0, le=86_400, description=GRANULARITY_DESC)


class WalkForwardInput(_Input):
    symbol: str = Field(description=SYMBOL_DESC)
    strategy: StrategySpec = Field(
        description="Strategy family to optimise. Its signal type is kept; its parameters are replaced by a grid search."
    )
    count: int = Field(20_000, ge=500, le=MAX_TICKS, description="Number of most recent ticks or candles.")
    granularity_s: int = Field(0, ge=0, le=86_400, description=GRANULARITY_DESC)
    n_folds: int = Field(4, ge=2, le=8, description="Number of train/test folds.")


# --------------------------------------------------------------------------- helpers

@dataclass
class ToolOutput:
    llm: dict[str, Any]
    ui: dict[str, Any] | None = None


def compact(obj: Any) -> Any:
    """JSON-safe copy with floats trimmed to 6 significant digits and private keys dropped."""
    if isinstance(obj, dict):
        return {k: compact(v) for k, v in obj.items() if not str(k).startswith("_")}
    if isinstance(obj, (list, tuple)):
        return [compact(v) for v in obj]
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (float, np.floating)):
        f = float(obj)
        return None if not math.isfinite(f) else float(f"{f:.6g}")
    return obj


def _series(market: SyntheticMarket, symbol: str, count: int, granularity_s: int) -> tuple[np.ndarray, np.ndarray]:
    if granularity_s == 0:
        return market.history(symbol, count)
    candles = market.candles(symbol, granularity_s, count)
    return (
        np.array([c["epoch"] for c in candles], dtype=np.int64),
        np.array([c["close"] for c in candles], dtype=float),
    )


def _span(epochs: np.ndarray) -> dict[str, Any]:
    return {"start_epoch": int(epochs[0]), "end_epoch": int(epochs[-1]), "minutes": round((epochs[-1] - epochs[0]) / 60, 1)}


# --------------------------------------------------------------------------- handlers

async def list_symbols(market: SyntheticMarket, _: ListSymbolsInput) -> ToolOutput:
    rows = market.symbols()
    return ToolOutput(llm={"symbols": rows}, ui={"kind": "symbols", "rows": rows})


async def price_summary(market: SyntheticMarket, args: PriceSummaryInput) -> ToolOutput:
    epochs, prices = _series(market, args.symbol, args.count, args.granularity_s)
    stats = {
        "symbol": market.feed(args.symbol).spec.symbol,
        "points": len(prices),
        "granularity_s": args.granularity_s,
        **_span(epochs),
        "first": prices[0],
        "last": prices[-1],
        "change_pct": (prices[-1] / prices[0] - 1) * 100,
        "high": prices.max(),
        "low": prices.min(),
    }
    return ToolOutput(
        llm={**stats, "path_sample": [round(float(p), 6) for p in prices[:: max(1, len(prices) // 20)]]},
        ui={"kind": "prices", **compact(stats), "series": downsample(epochs, prices)},
    )


async def volatility(market: SyntheticMarket, args: VolatilityInput) -> ToolOutput:
    spec = market.feed(args.symbol).spec
    epochs, prices = market.history(spec.symbol, args.count)
    report = await asyncio.to_thread(volatility_report, epochs, prices, args.window)
    roll_epochs, roll = report["_rolling"]
    llm = {"symbol": spec.symbol, "design_vol": spec.design_vol, **_span(epochs), **report}
    return ToolOutput(
        llm=llm,
        ui={"kind": "volatility", **compact(llm), "series": downsample(roll_epochs, roll)},
    )


async def regime(market: SyntheticMarket, args: RegimeInput) -> ToolOutput:
    spec = market.feed(args.symbol).spec
    epochs, prices = market.history(spec.symbol, args.count)
    result = await asyncio.to_thread(detect_regimes, epochs, prices, args.window)
    vol_epochs, vol = result["_rolling"]
    llm = {"symbol": spec.symbol, **_span(epochs), **result}
    return ToolOutput(llm=llm, ui={"kind": "regime", **compact(llm), "series": downsample(vol_epochs, vol)})


async def compare_volatility(market: SyntheticMarket, args: CompareInput) -> ToolOutput:
    if args.symbols:
        symbols = list(dict.fromkeys(market.feed(s).spec.symbol for s in args.symbols))
    else:
        symbols = [row["symbol"] for row in market.symbols()]
    snapshots = {s: market.history(s, args.count) for s in symbols}

    def compute() -> list[dict[str, Any]]:
        rows = []
        for sym, (epochs, prices) in snapshots.items():
            returns = log_returns(prices)
            per_year = periods_per_year(epochs)
            roll = rolling_vol(returns, min(args.window, len(returns) // 4), per_year)
            valid = roll[~np.isnan(roll)]
            current = float(valid[-1])
            rows.append(
                {
                    "symbol": sym,
                    "design_vol": market.feed(sym).spec.design_vol,
                    "realized_vol": realized_vol(returns, per_year),
                    "current_vol": current,
                    "current_percentile": float((valid < current).mean() * 100),
                }
            )
        return sorted(rows, key=lambda r: r["current_vol"])

    rows = await asyncio.to_thread(compute)
    llm = {"window": args.window, "ticks_per_symbol": args.count, "sorted_calmest_first": rows}
    return ToolOutput(llm=llm, ui={"kind": "compare", **compact(llm)})


async def backtest(market: SyntheticMarket, args: BacktestInput) -> ToolOutput:
    symbol = market.feed(args.symbol).spec.symbol
    epochs, prices = _series(market, symbol, args.count, args.granularity_s)
    result = await asyncio.to_thread(run_backtest, epochs, prices, args.strategy)
    llm = {"symbol": symbol, "granularity_s": args.granularity_s, **_span(epochs), **result}
    ui = {"kind": "backtest", **compact(llm), "strategy": args.strategy.model_dump(), **result["_curves"]}
    return ToolOutput(llm=llm, ui=ui)


async def walk_forward_optimize(market: SyntheticMarket, args: WalkForwardInput) -> ToolOutput:
    symbol = market.feed(args.symbol).spec.symbol
    epochs, prices = _series(market, symbol, args.count, args.granularity_s)
    result = await asyncio.to_thread(walk_forward, epochs, prices, args.strategy, args.n_folds)
    llm = {"symbol": symbol, "granularity_s": args.granularity_s, "signal_type": args.strategy.signal.type, **result}
    ui = {"kind": "walk_forward", **compact(llm), **result["_curves"]}
    return ToolOutput(llm=llm, ui=ui)


# --------------------------------------------------------------------------- registry

@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    input_model: type[_Input]
    handler: Callable[[SyntheticMarket, Any], Awaitable[ToolOutput]]


TOOLS: dict[str, Tool] = {
    t.name: t
    for t in (
        Tool(
            "list_symbols",
            "List every synthetic index in the market with its category, tick interval, design volatility "
            "(where the model has one), description and last price.",
            ListSymbolsInput,
            list_symbols,
        ),
        Tool(
            "get_price_summary",
            "Summarise recent price action for one index: first/last/high/low, % change, time span, and a "
            "coarse sample of the path. Use for questions like 'what has VOL75 done in the last hour?'.",
            PriceSummaryInput,
            price_summary,
        ),
        Tool(
            "volatility_report",
            "Volatility analysis for one index: full-sample realized volatility, current rolling volatility "
            "and its percentile versus the sample, EWMA, a GARCH(1,1) forecast, count of jumps (>6 robust "
            "sigma) and the largest single move. All volatilities are annualised decimals (0.75 = 75%). "
            "Use to explain spikes or compare estimated against design volatility.",
            VolatilityInput,
            volatility,
        ),
        Tool(
            "detect_regime",
            "Label calm / normal / turbulent volatility regimes for one index. A period only counts as calm "
            "or turbulent if rolling volatility moves beyond what sampling noise explains, so a "
            "constant-volatility index correctly shows a single regime.",
            RegimeInput,
            regime,
        ),
        Tool(
            "compare_volatility",
            "Rank several indices (or all of them) by current rolling volatility, calmest first, with "
            "realized and design volatility for each. Use for 'which index is calmest/wildest right now?'.",
            CompareInput,
            compare_volatility,
        ),
        Tool(
            "run_backtest",
            "Backtest a strategy on one index. Returns net-of-cost metrics for the full sample, in-sample "
            "(first 70%) and out-of-sample (last 30%): total return, Sharpe, max drawdown, trade count, win "
            "rate, exposure, buy-and-hold return, and a circular-shift significance test (p-value: how "
            "often randomly re-timed copies of the same positions did as well). Includes a plain-language verdict.",
            BacktestInput,
            backtest,
        ),
        Tool(
            "walk_forward_optimize",
            "Walk-forward optimisation: grid-search the parameters of a strategy family on each training "
            "window, then trade the winner unchanged on the next window. Shows how much optimised "
            "in-sample performance survives out-of-sample. Use when the user asks to optimise or tune a strategy.",
            WalkForwardInput,
            walk_forward_optimize,
        ),
    )
}


def _inline_refs(schema: dict[str, Any]) -> dict[str, Any]:
    """Inline pydantic's $defs/$ref and drop keys that only add noise for the model."""
    defs = schema.pop("$defs", {})

    def resolve(node: Any) -> Any:
        if isinstance(node, dict):
            if "$ref" in node:
                return resolve(defs[node["$ref"].split("/")[-1]])
            return {k: resolve(v) for k, v in node.items() if k not in ("title", "discriminator")}
        if isinstance(node, list):
            return [resolve(v) for v in node]
        return node

    return resolve(schema)


def tool_definitions() -> list[dict[str, Any]]:
    return [
        {
            "name": t.name,
            "description": t.description,
            "input_schema": _inline_refs(t.input_model.model_json_schema()),
            "eager_input_streaming": True,
        }
        for t in TOOLS.values()
    ]


@dataclass
class ToolResult:
    name: str
    content: str  # JSON sent back to Claude
    is_error: bool
    ui: dict[str, Any] | None


async def execute_tool(market: SyntheticMarket, name: str, raw_input: Any) -> ToolResult:
    """Validate and run one tool call. Failures come back as error results Claude can recover from."""
    tool = TOOLS.get(name)
    if tool is None:
        return ToolResult(name, json.dumps({"error": f"Unknown tool '{name}'."}), True, None)
    try:
        args = tool.input_model.model_validate(raw_input if isinstance(raw_input, dict) else {})
        out = await tool.handler(market, args)
    except ValidationError as exc:
        errors = [{"loc": ".".join(map(str, e["loc"])), "msg": e["msg"]} for e in exc.errors(include_url=False)]
        return ToolResult(name, json.dumps({"error": "Invalid input", "details": errors}), True, None)
    except (UnknownSymbolError, ValueError) as exc:
        return ToolResult(name, json.dumps({"error": str(exc)}), True, None)
    return ToolResult(name, json.dumps(compact(out.llm)), False, out.ui)
