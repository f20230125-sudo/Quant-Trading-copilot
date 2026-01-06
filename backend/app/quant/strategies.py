"""A small, validated strategy language.

The copilot never generates executable code. It fills in one of these
pydantic models, which are validated before anything runs. Every signal is
computed only from data available at the bar's close, so there is no look-ahead.
"""

from __future__ import annotations

from typing import Annotated, Literal, Self

import numpy as np
import pandas as pd
from pydantic import BaseModel, ConfigDict, Field, model_validator


class SmaCross(BaseModel):
    """Long when the fast SMA is above the slow SMA, short when below."""

    model_config = ConfigDict(extra="forbid")
    type: Literal["sma_cross"]
    fast: int = Field(ge=2, le=1000)
    slow: int = Field(ge=3, le=5000)

    @model_validator(mode="after")
    def _fast_below_slow(self) -> Self:
        if self.fast >= self.slow:
            raise ValueError("fast period must be shorter than slow period")
        return self


class RsiThreshold(BaseModel):
    """Enter when RSI crosses a threshold, exit when it returns to 50.

    mean_reversion: buy oversold (< lower), sell overbought (> upper).
    momentum: buy strength (> upper), sell weakness (< lower).
    """

    model_config = ConfigDict(extra="forbid")
    type: Literal["rsi"]
    period: int = Field(14, ge=2, le=500)
    lower: float = Field(30, gt=0, lt=50)
    upper: float = Field(70, gt=50, lt=100)
    mode: Literal["mean_reversion", "momentum"] = "mean_reversion"


class Breakout(BaseModel):
    """Donchian channel stop-and-reverse: long on a new ``lookback`` high, short on a new low."""

    model_config = ConfigDict(extra="forbid")
    type: Literal["breakout"]
    lookback: int = Field(ge=5, le=5000)


Signal = Annotated[SmaCross | RsiThreshold | Breakout, Field(discriminator="type")]


class StrategySpec(BaseModel):
    model_config = ConfigDict(extra="forbid")
    signal: Signal
    direction: Literal["long_only", "short_only", "long_short"] = "long_short"
    stop_loss_pct: float | None = Field(None, gt=0, le=50)
    take_profit_pct: float | None = Field(None, gt=0, le=100)
    fee_bps: float = Field(1.0, ge=0, le=100, description="cost per unit of turnover, in basis points")

    def warmup(self) -> int:
        sig = self.signal
        if isinstance(sig, SmaCross):
            return sig.slow
        if isinstance(sig, RsiThreshold):
            return sig.period
        return sig.lookback


def rsi(prices: np.ndarray, period: int) -> np.ndarray:
    """Wilder's RSI. NaN until ``period`` changes have been observed."""
    delta = pd.Series(prices, dtype=float).diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    rs = gain / loss
    out = 100 - 100 / (1 + rs)
    out[(loss == 0) & gain.notna()] = 100.0
    return out.to_numpy()


def _sma_cross(prices: np.ndarray, sig: SmaCross) -> np.ndarray:
    s = pd.Series(prices, dtype=float)
    fast = s.rolling(sig.fast).mean().to_numpy()
    slow = s.rolling(sig.slow).mean().to_numpy()
    target = np.where(fast > slow, 1, np.where(fast < slow, -1, 0))
    target[np.isnan(slow)] = 0
    return target


def _rsi(prices: np.ndarray, sig: RsiThreshold) -> np.ndarray:
    values = rsi(prices, sig.period)
    target = np.zeros(len(prices), dtype=int)
    pos = 0
    for t, v in enumerate(values):
        if np.isnan(v):
            continue
        if sig.mode == "mean_reversion":
            if pos == 0:
                pos = 1 if v < sig.lower else -1 if v > sig.upper else 0
            elif (pos == 1 and v >= 50) or (pos == -1 and v <= 50):
                pos = 0
        else:
            if pos == 0:
                pos = 1 if v > sig.upper else -1 if v < sig.lower else 0
            elif (pos == 1 and v <= 50) or (pos == -1 and v >= 50):
                pos = 0
        target[t] = pos
    return target


def _breakout(prices: np.ndarray, sig: Breakout) -> np.ndarray:
    s = pd.Series(prices, dtype=float)
    # Channel from the previous `lookback` bars, excluding the current one.
    upper = s.rolling(sig.lookback).max().shift(1).to_numpy()
    lower = s.rolling(sig.lookback).min().shift(1).to_numpy()
    target = np.zeros(len(prices), dtype=int)
    pos = 0
    for t in range(len(prices)):
        if not np.isnan(upper[t]):
            if prices[t] > upper[t]:
                pos = 1
            elif prices[t] < lower[t]:
                pos = -1
        target[t] = pos
    return target


def target_positions(prices: np.ndarray, spec: StrategySpec) -> np.ndarray:
    """Desired position after observing the close of each bar, in {-1, 0, 1}."""
    sig = spec.signal
    if isinstance(sig, SmaCross):
        target = _sma_cross(prices, sig)
    elif isinstance(sig, RsiThreshold):
        target = _rsi(prices, sig)
    else:
        target = _breakout(prices, sig)

    if spec.direction == "long_only":
        target = np.maximum(target, 0)
    elif spec.direction == "short_only":
        target = np.minimum(target, 0)
    return target.astype(int)
