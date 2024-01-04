import numpy as np
import pytest
from pydantic import ValidationError

from app.quant.strategies import StrategySpec, rsi, target_positions

from .conftest import random_walk


def test_parses_json_the_llm_would_send():
    spec = StrategySpec.model_validate(
        {"signal": {"type": "sma_cross", "fast": 20, "slow": 50}, "direction": "long_only", "stop_loss_pct": 1.5}
    )
    assert spec.signal.fast == 20
    assert spec.fee_bps == 1.0


@pytest.mark.parametrize(
    "payload",
    [
        {"signal": {"type": "sma_cross", "fast": 50, "slow": 20}},  # fast >= slow
        {"signal": {"type": "sma_cross", "fast": 5, "slow": 20, "code": "import os"}},  # extra field
        {"signal": {"type": "macd"}},  # unknown signal
        {"signal": {"type": "rsi", "lower": 60}},  # lower must be < 50
        {"signal": {"type": "breakout", "lookback": 20}, "stop_loss_pct": -1},
        {"signal": {"type": "breakout", "lookback": 20}, "leverage": 100},  # unknown top-level field
    ],
)
def test_rejects_invalid_specs(payload):
    with pytest.raises(ValidationError):
        StrategySpec.model_validate(payload)


def test_rsi_extremes():
    up = np.arange(1, 60, dtype=float)
    down = up[::-1].copy()
    assert rsi(up, 14)[-1] == pytest.approx(100.0)
    assert rsi(down, 14)[-1] == pytest.approx(0.0)
    assert np.isnan(rsi(up, 14)[:14]).all()


@pytest.mark.parametrize(
    "signal",
    [
        {"type": "sma_cross", "fast": 10, "slow": 40},
        {"type": "rsi", "period": 14, "mode": "mean_reversion"},
        {"type": "rsi", "period": 14, "mode": "momentum"},
        {"type": "breakout", "lookback": 30},
    ],
)
def test_no_lookahead(signal):
    """A signal computed on data up to bar k must equal the full-history signal at bar k."""
    _, prices = random_walk(n=1500, seed=3)
    spec = StrategySpec.model_validate({"signal": signal})
    full = target_positions(prices, spec)
    for k in (100, 437, 900, 1499):
        assert (target_positions(prices[: k + 1], spec) == full[: k + 1]).all()


def test_direction_filters():
    _, prices = random_walk(n=1000, seed=1)
    base = {"signal": {"type": "sma_cross", "fast": 5, "slow": 20}}
    longs = target_positions(prices, StrategySpec.model_validate({**base, "direction": "long_only"}))
    shorts = target_positions(prices, StrategySpec.model_validate({**base, "direction": "short_only"}))
    assert set(np.unique(longs)) <= {0, 1}
    assert set(np.unique(shorts)) <= {-1, 0}
