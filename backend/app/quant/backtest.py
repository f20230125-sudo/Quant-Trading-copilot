"""Backtesting engine with honest baselines.

Signals are vectorised (see strategies.py); execution walks the bars once so
that stop-loss / take-profit exits, which are path dependent, are handled
exactly. Timing convention: a position decided at the close of bar t earns the
return from t to t+1. Stops are checked on closes and fill at the close,
because the input is tick or candle-close data.

Every result is compared against a circular-shift null: the strategy's own
position series is rotated in time many times, which keeps its exposure,
turnover and holding periods but breaks any link to the prices. If the real
alignment doesn't beat most rotations, there is no evidence of an edge.
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np

from .series import downsample
from .strategies import Breakout, RsiThreshold, SmaCross, StrategySpec, target_positions
from .volatility import periods_per_year

MIN_BARS_AFTER_WARMUP = 50
MIN_TRADES_FOR_VERDICT = 10


def execute(prices: np.ndarray, target: np.ndarray, spec: StrategySpec) -> np.ndarray:
    """Turn target positions into held positions, applying stop-loss / take-profit.

    After a stop or target exit, the strategy stays flat until the signal changes,
    so it doesn't immediately re-enter the trade it just closed.
    """
    sl, tp = spec.stop_loss_pct, spec.take_profit_pct
    positions = np.zeros(len(prices), dtype=int)
    pos, entry, blocked = 0, math.nan, 0
    for t, price in enumerate(prices):
        if pos != 0 and (sl or tp):
            move_pct = pos * (price / entry - 1) * 100
            if (sl and move_pct <= -sl) or (tp and move_pct >= tp):
                blocked, pos = pos, 0
        desired = int(target[t])
        if blocked and desired != blocked:
            blocked = 0
        if blocked:
            desired = 0
        if desired != pos:
            pos, entry = desired, price
        positions[t] = pos
    return positions


def simple_returns(prices: np.ndarray) -> np.ndarray:
    r = np.zeros(len(prices))
    r[1:] = prices[1:] / prices[:-1] - 1
    return r


def net_returns(positions: np.ndarray, returns: np.ndarray, fee_bps: float) -> np.ndarray:
    held = np.zeros(len(positions))
    held[1:] = positions[:-1]
    turnover = np.abs(np.diff(positions, prepend=0))
    return held * returns - turnover * fee_bps / 1e4


def sharpe(net: np.ndarray, per_year: float) -> float:
    if len(net) < 2:
        return 0.0
    sd = float(np.std(net, ddof=1))
    return float(np.mean(net) / sd * math.sqrt(per_year)) if sd > 0 else 0.0


def metrics(net: np.ndarray, per_year: float) -> dict[str, float]:
    equity = np.concatenate([[1.0], np.cumprod(1 + net)])
    drawdown = equity / np.maximum.accumulate(equity) - 1
    return {
        "total_return": float(equity[-1] - 1),
        "sharpe": sharpe(net, per_year),
        "max_drawdown": float(drawdown.min()),
        "bars": int(len(net)),
    }


def trade_list(positions: np.ndarray, returns: np.ndarray, fee_bps: float) -> list[dict[str, Any]]:
    """Round trips, each with its compounded return net of entry and exit costs."""
    trades = []
    n = len(positions)
    t = 0
    while t < n:
        direction = positions[t]
        if direction != 0 and (t == 0 or positions[t - 1] != direction):
            end = t
            while end + 1 < n and positions[end + 1] == direction:
                end += 1
            # Held from the close of t to the close of end+1 (or the last bar if still open).
            exit_bar = min(end + 1, n - 1)
            gross = float(np.prod(1 + direction * returns[t + 1 : exit_bar + 1]) - 1)
            closed = end + 1 < n
            cost = fee_bps / 1e4 * (2 if closed else 1)
            trades.append(
                {"entry": t, "exit": exit_bar, "direction": int(direction), "return": gross - cost, "open": not closed}
            )
            t = end + 1
        else:
            t += 1
    return trades


def shift_null_test(
    positions: np.ndarray, returns: np.ndarray, fee_bps: float, n_sims: int = 500, seed: int = 7
) -> dict[str, float]:
    """p-value of the strategy's log return against circularly shifted copies of its positions."""
    n = len(positions)
    actual = float(np.log1p(net_returns(positions, returns, fee_bps)).sum())
    if n < 20 or not positions.any():
        return {"p_value": 1.0, "null_mean_return": 0.0, "null_p95_return": 0.0, "n_sims": 0}
    rng = np.random.default_rng(seed)
    shifts = rng.integers(n // 10, n - n // 10, size=n_sims)
    sims = np.array(
        [np.log1p(net_returns(np.roll(positions, s), returns, fee_bps)).sum() for s in shifts]
    )
    return {
        "p_value": float((1 + np.sum(sims >= actual)) / (1 + n_sims)),
        "null_mean_return": float(np.expm1(sims.mean())),
        "null_p95_return": float(np.expm1(np.percentile(sims, 95))),
        "n_sims": int(n_sims),
    }


def _verdict(n_trades: int, p_value: float, net_return: float, oos_return: float, fee_bps: float) -> str:
    if n_trades < MIN_TRADES_FOR_VERDICT:
        return f"Inconclusive: only {n_trades} trades, too few to judge."
    if p_value < 0.05 and net_return > 0 and oos_return > 0:
        return (
            f"Possible edge (p={p_value:.3f}) that stayed profitable after costs and held "
            "out-of-sample. Treat with caution: this is one test among many you could run."
        )
    if p_value < 0.05:
        return (
            f"The entry timing is statistically better than random (p={p_value:.3f}), but the edge "
            f"does not survive costs of {fee_bps:g} bp per unit of turnover: the strategy loses "
            "money net of fees or out-of-sample."
        )
    return (
        f"No statistically significant edge (p={p_value:.2f}). Performance is consistent with "
        "random entry timing at the same exposure and turnover."
    )


def run_backtest(
    epochs: np.ndarray, prices: np.ndarray, spec: StrategySpec, holdout_frac: float = 0.3
) -> dict[str, Any]:
    epochs = np.asarray(epochs)
    prices = np.asarray(prices, dtype=float)
    n = len(prices)
    if n < spec.warmup() + MIN_BARS_AFTER_WARMUP:
        raise ValueError(
            f"Not enough data: this strategy needs at least {spec.warmup() + MIN_BARS_AFTER_WARMUP} "
            f"bars but only {n} were loaded. Request more history or use shorter periods."
        )

    per_year = periods_per_year(epochs)
    returns = simple_returns(prices)
    positions = execute(prices, target_positions(prices, spec), spec)
    net = net_returns(positions, returns, spec.fee_bps)
    split = int(n * (1 - holdout_frac))

    trades = trade_list(positions, returns, spec.fee_bps)
    trade_returns = np.array([tr["return"] for tr in trades]) if trades else np.array([])
    null = shift_null_test(positions, returns, spec.fee_bps)
    full = metrics(net, per_year)
    out_of_sample = metrics(net[split:], per_year)

    equity = np.cumprod(1 + net)
    buy_hold = prices / prices[0]
    return {
        "bars": n,
        "sampling_interval_s": float(np.median(np.diff(epochs))) if n > 1 else 0.0,
        "full": full,
        "in_sample": metrics(net[:split], per_year),
        "out_of_sample": out_of_sample,
        "split_epoch": int(epochs[split]),
        "n_trades": len(trades),
        "win_rate": float((trade_returns > 0).mean()) if len(trades) else 0.0,
        "avg_trade_return": float(trade_returns.mean()) if len(trades) else 0.0,
        "exposure": float((positions != 0).mean()),
        "buy_and_hold_return": float(prices[-1] / prices[0] - 1),
        "null_test": null,
        "fee_bps": spec.fee_bps,
        "verdict": _verdict(
            len(trades), null["p_value"], full["total_return"], out_of_sample["total_return"], spec.fee_bps
        ),
        "_curves": {
            "equity": downsample(epochs, equity),
            "buy_hold": downsample(epochs, buy_hold),
        },
    }


# ---------------------------------------------------------------- walk-forward

def _grid(spec: StrategySpec) -> list[StrategySpec]:
    sig = spec.signal
    if isinstance(sig, SmaCross):
        params = [{"fast": f, "slow": s} for f in (5, 10, 20, 50) for s in (30, 50, 100, 200) if f < s]
    elif isinstance(sig, RsiThreshold):
        params = [{"period": p, "lower": lo, "upper": 100 - lo} for p in (7, 14, 28) for lo in (20, 25, 30)]
    elif isinstance(sig, Breakout):
        params = [{"lookback": lb} for lb in (20, 50, 100, 200, 400)]
    else:  # pragma: no cover
        raise TypeError(type(sig))
    return [spec.model_copy(update={"signal": sig.model_copy(update=p)}) for p in params]


def _signal_params(spec: StrategySpec) -> dict[str, Any]:
    return spec.signal.model_dump(exclude={"type"})


def walk_forward(
    epochs: np.ndarray, prices: np.ndarray, spec: StrategySpec, n_folds: int = 4
) -> dict[str, Any]:
    """Rolling walk-forward optimisation over a small parameter grid.

    The series is cut into n_folds + 1 consecutive chunks. For each fold, the
    parameters with the best Sharpe on chunk k-1 are traded, unchanged, on
    chunk k. The gap between in-sample and out-of-sample Sharpe measures how
    much of the optimised performance was curve-fitting.
    """
    epochs = np.asarray(epochs)
    prices = np.asarray(prices, dtype=float)
    n = len(prices)
    if n < 500:
        raise ValueError(f"Walk-forward needs at least 500 bars; only {n} were loaded.")

    per_year = periods_per_year(epochs)
    returns = simple_returns(prices)
    candidates = _grid(spec)
    # Signals only look backwards, so running each candidate once over the full
    # series and slicing it gives the same result as re-running per window.
    nets = [
        net_returns(execute(prices, target_positions(prices, c), c), returns, c.fee_bps)
        for c in candidates
    ]

    chunks = np.array_split(np.arange(n), n_folds + 1)
    folds, oos_pieces = [], []
    for k in range(1, n_folds + 1):
        train, test = chunks[k - 1], chunks[k]
        scores = [sharpe(net[train], per_year) for net in nets]
        best = int(np.argmax(scores))
        oos_pieces.append(nets[best][test])
        folds.append(
            {
                "fold": k,
                "train_start": int(epochs[train[0]]),
                "test_start": int(epochs[test[0]]),
                "test_end": int(epochs[test[-1]]),
                "chosen_params": _signal_params(candidates[best]),
                "in_sample_sharpe": scores[best],
                "out_of_sample_sharpe": sharpe(nets[best][test], per_year),
                "out_of_sample_return": metrics(nets[best][test], per_year)["total_return"],
            }
        )

    oos = metrics(np.concatenate(oos_pieces), per_year)
    mean_is = float(np.mean([f["in_sample_sharpe"] for f in folds]))
    if mean_is > 0 and oos["sharpe"] < 0.5 * mean_is:
        verdict = (
            f"Optimised in-sample Sharpe averaged {mean_is:.2f} but out-of-sample Sharpe was "
            f"{oos['sharpe']:.2f}. Most of the in-sample performance came from fitting noise."
        )
    elif oos["sharpe"] > 0:
        verdict = (
            f"Out-of-sample Sharpe of {oos['sharpe']:.2f} retained at least half of the in-sample "
            "level. Worth re-testing on fresh data before trusting it."
        )
    else:
        verdict = "No parameter set was profitable even in-sample after costs."

    return {
        "bars": n,
        "n_folds": n_folds,
        "grid_size": len(candidates),
        "folds": folds,
        "mean_in_sample_sharpe": mean_is,
        "out_of_sample": oos,
        "verdict": verdict,
        "_curves": {"oos_equity": downsample(epochs[chunks[1][0]:], np.cumprod(1 + np.concatenate(oos_pieces)))},
    }
