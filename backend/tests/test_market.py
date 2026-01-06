import asyncio

import numpy as np
import pytest

from app.market import CATALOG, SyntheticMarket, UnknownSymbolError
from app.quant.backtest import run_backtest
from app.quant.regime import detect_regimes
from app.quant.strategies import StrategySpec
from app.quant.volatility import detect_jumps, log_returns, realized_vol, periods_per_year

NOW = 1_800_000_000


@pytest.fixture
def market():
    return SyntheticMarket(seed=42, history_size=20_000, now=NOW)


def test_same_seed_same_history():
    a = SyntheticMarket(seed=7, history_size=1000, now=NOW)
    b = SyntheticMarket(seed=7, history_size=1000, now=NOW)
    c = SyntheticMarket(seed=8, history_size=1000, now=NOW)
    assert np.array_equal(a.history("VOL75", 1000)[1], b.history("VOL75", 1000)[1])
    assert not np.array_equal(a.history("VOL75", 1000)[1], c.history("VOL75", 1000)[1])


def test_history_ends_now_at_the_index_interval(market):
    epochs, prices = market.history("VOL100_1S", 500)
    assert len(prices) == 500 and epochs[-1] == NOW
    assert set(np.diff(epochs)) == {1}
    assert set(np.diff(market.history("VOL75", 500)[0])) == {2}


@pytest.mark.parametrize("symbol,sigma", [("VOL10", 0.10), ("VOL25", 0.25), ("VOL75", 0.75), ("VOL100_1S", 1.0)])
def test_volatility_indices_match_their_design(market, symbol, sigma):
    epochs, prices = market.history(symbol, 20_000)
    assert realized_vol(log_returns(prices), periods_per_year(epochs)) == pytest.approx(sigma, rel=0.03)


def test_step_index_moves_exactly_one_step(market):
    _, prices = market.history("STEP", 1000)
    assert np.allclose(np.abs(np.diff(prices)), 0.1)
    assert len(detect_jumps(log_returns(prices))) == 0


def test_regime_index_has_detectable_regimes(market):
    epochs, prices = market.history("REGIME", 20_000)
    assert detect_regimes(epochs, prices)["time_share"]["normal"] < 0.9


def test_jump_index_has_jumps(market):
    _, prices = market.history("JUMP50", 20_000)
    assert len(detect_jumps(log_returns(prices))) >= 5


def test_backtester_finds_planted_edge_and_only_there(market):
    fast = StrategySpec.model_validate({"signal": {"type": "sma_cross", "fast": 2, "slow": 5}, "fee_bps": 0})
    planted = run_backtest(*market.history("MOMENTUM50", 20_000), fast)
    control = run_backtest(*market.history("VOL50", 20_000), fast)
    assert planted["null_test"]["p_value"] < 0.01
    assert control["null_test"]["p_value"] > 0.05


def test_costs_can_erase_a_real_edge(market):
    costly = StrategySpec.model_validate({"signal": {"type": "sma_cross", "fast": 2, "slow": 5}, "fee_bps": 1})
    result = run_backtest(*market.history("MOMENTUM50", 20_000), costly)
    assert result["null_test"]["p_value"] < 0.01
    assert "does not survive costs" in result["verdict"]


def test_tick_until_advances_every_feed_on_its_own_clock(market):
    emitted = market.tick_until(NOW + 10)
    per_feed = {spec.symbol: 10 // spec.interval_s for spec in CATALOG}
    assert emitted == sum(per_feed.values())
    assert market.history("VOL75", 1)[0][-1] == NOW + 10
    assert market.history("STEP", 1)[0][-1] == NOW + 10


def test_listeners_receive_ticks(market):
    async def scenario():
        async with market.listen("vol75") as queue:  # case-insensitive
            market.tick_until(NOW + 4)
            ticks = [queue.get_nowait() for _ in range(queue.qsize())]
        return ticks

    ticks = asyncio.run(scenario())
    assert [t["epoch"] for t in ticks] == [NOW + 2, NOW + 4]
    assert market.feed("VOL75").listeners == set()


def test_unknown_symbol_suggests_close_matches(market):
    with pytest.raises(UnknownSymbolError) as exc:
        market.history("VOL57", 10)
    assert "VOL75" in exc.value.suggestions or "VOL50" in exc.value.suggestions


def test_candles_aggregate_ticks(market):
    candles = market.candles("VOL75", 60, 100)
    assert len(candles) == 100
    assert all(c["low"] <= min(c["open"], c["close"]) and c["high"] >= max(c["open"], c["close"]) for c in candles)
    assert all(b["epoch"] - a["epoch"] == 60 for a, b in zip(candles, candles[1:]))
