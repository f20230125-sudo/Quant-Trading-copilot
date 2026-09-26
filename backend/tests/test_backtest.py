import numpy as np
import pytest

from app.quant.backtest import (
    execute,
    net_returns,
    run_backtest,
    shift_null_test,
    simple_returns,
    trade_list,
    walk_forward,
)
from app.quant.strategies import StrategySpec

from .conftest import random_walk

PRICES = np.array([100.0, 101.0, 102.0, 101.0, 103.0])


def spec(**overrides):
    return StrategySpec.model_validate({"signal": {"type": "sma_cross", "fast": 2, "slow": 3}, **overrides})


def test_hand_computed_five_bars():
    positions = np.array([0, 1, 1, -1, 0])
    r = simple_returns(PRICES)
    net = net_returns(positions, r, fee_bps=0)
    # Long is decided at the close of bar 1, so it first earns bar 2's return.
    expected = [0, 0, 102 / 101 - 1, 101 / 102 - 1, -(103 / 101 - 1)]
    np.testing.assert_allclose(net, expected)


def test_costs_scale_with_turnover():
    positions = np.array([0, 1, 1, -1, 0])  # turnover 1, 0, 2, 1 -> 4 units
    r = simple_returns(PRICES)
    gross = net_returns(positions, r, fee_bps=0)
    net = net_returns(positions, r, fee_bps=10)
    np.testing.assert_allclose(gross - net, [0, 0.001, 0, 0.002, 0.001])


def test_flat_prices_give_zero_pnl_before_costs():
    prices = np.full(200, 50.0)
    positions = np.tile([1, 1, -1, -1, 0], 40)
    net = net_returns(positions, simple_returns(prices), fee_bps=0)
    assert np.allclose(net, 0)


def test_stop_loss_exits_and_stays_flat_until_signal_changes():
    prices = np.array([100, 100, 99, 98, 97, 96, 97, 98], dtype=float)
    target = np.array([1, 1, 1, 1, 1, 1, 0, 1])
    positions = execute(prices, target, spec(stop_loss_pct=1.5))
    # Enters at 100 on bar 0; bar 3 is -2% -> stopped out. Re-enters only after the signal resets.
    assert positions.tolist() == [1, 1, 1, 0, 0, 0, 0, 1]


def test_take_profit():
    prices = np.array([100, 101, 102, 103], dtype=float)
    positions = execute(prices, np.array([1, 1, 1, 1]), spec(take_profit_pct=1.5))
    assert positions.tolist() == [1, 1, 0, 0]


def test_trade_list_returns_include_costs():
    positions = np.array([0, 1, 1, 0, -1])
    trades = trade_list(positions, simple_returns(PRICES), fee_bps=10)
    assert len(trades) == 2
    first, second = trades
    assert first["direction"] == 1 and first["entry"] == 1 and first["exit"] == 3
    assert first["return"] == pytest.approx((101 / 101) - 1 - 0.002)
    assert second["open"] is True and second["return"] == pytest.approx(-0.001)


def test_null_test_detects_perfect_foresight():
    _, prices = random_walk(n=3000, seed=5)
    r = simple_returns(prices)
    cheat = np.sign(np.append(r[1:], 0)).astype(int)  # knows the next return
    assert shift_null_test(cheat, r, fee_bps=0)["p_value"] < 0.01


def test_random_walk_has_no_edge(walk):
    epochs, prices = walk
    result = run_backtest(epochs, prices, spec(signal={"type": "sma_cross", "fast": 20, "slow": 50}))
    assert result["n_trades"] > 10
    assert "No statistically significant edge" in result["verdict"]
    assert result["full"]["max_drawdown"] <= 0
    assert result["sampling_interval_s"] == 2.0
    assert len(result["_curves"]["equity"]) <= 300


def test_insufficient_data_is_a_clear_error():
    epochs, prices = random_walk(n=100)
    with pytest.raises(ValueError, match="Not enough data"):
        run_backtest(epochs, prices, spec(signal={"type": "sma_cross", "fast": 20, "slow": 200}))


def test_walk_forward_structure(walk):
    epochs, prices = walk
    result = walk_forward(epochs, prices, spec(signal={"type": "breakout", "lookback": 50}))
    assert result["n_folds"] == 4 and len(result["folds"]) == 4
    assert result["grid_size"] == 5
    assert all(f["test_start"] > f["train_start"] for f in result["folds"])
    assert isinstance(result["verdict"], str)
