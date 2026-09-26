import asyncio

import pytest

import app.agent.local as local
from app.agent.parse import find_symbols, parse, parse_strategy
from app.market import SyntheticMarket

NOW = 1_800_000_000


@pytest.fixture(scope="module")
def market():
    return SyntheticMarket(seed=5, history_size=20_000, now=NOW)


@pytest.fixture(autouse=True)
def no_typing_delay(monkeypatch):
    monkeypatch.setattr(local, "TYPE_DELAY_S", 0)


# ----------------------------------------------------------------- parsing


@pytest.mark.parametrize(
    "text,expected",
    [
        ("how volatile is vol 75?", ["VOL75"]),
        ("Volatility 100 (1s) vs V100", ["VOL100_1S", "VOL100"]),
        ("compare jump 50, crash500 and the boom index", ["JUMP50", "CRASH500", "BOOM500"]),
        ("is STEP calmer than VOL10", ["STEP", "VOL10"]),
        ("take it step by step: what regime is VOL50 in?", ["VOL50"]),  # everyday words aren't symbols
        ("rsi momentum mode on MOMENTUM50", ["MOMENTUM50"]),
        ("a 50% stop on vol 50", ["VOL50"]),
    ],
)
def test_find_symbols(text, expected):
    assert find_symbols(text)[0] == expected


@pytest.mark.parametrize(
    "text,signal",
    [
        ("sma 20/50 crossover", {"type": "sma_cross", "fast": 20, "slow": 50}),
        ("moving average cross 50 and 10", {"type": "sma_cross", "fast": 10, "slow": 50}),
        ("a fast sma crossover", {"type": "sma_cross", "fast": 2, "slow": 5}),
        ("rsi(7) momentum 25/75", {"type": "rsi", "mode": "momentum", "period": 7, "lower": 25, "upper": 75}),
        ("rsi mean reversion", {"type": "rsi", "mode": "mean_reversion"}),
        ("a 120-tick breakout", {"type": "breakout", "lookback": 120}),
    ],
)
def test_parse_signal(text, signal):
    spec, named = parse_strategy(text)
    assert named and spec["signal"] == signal


def test_parse_modifiers():
    spec, named = parse_strategy("long only with a 1.5% stop-loss, take profit 3% and zero fees")
    assert not named
    assert spec == {"direction": "long_only", "stop_loss_pct": 1.5, "take_profit_pct": 3.0, "fee_bps": 0.0}
    assert parse_strategy("0.5 bps costs")[0]["fee_bps"] == 0.5


@pytest.mark.parametrize(
    "text,intents",
    [
        ("Which index is calmest right now?", ["compare"]),
        ("What's VOL75's volatility compared with its design?", ["volatility"]),
        ("Is REGIME calm or turbulent?", ["regime"]),
        ("Optimise an SMA crossover on VOL50", ["walk_forward"]),
        ("Compare a fast SMA crossover on MOMENTUM50 and VOL50", ["backtest"]),
        ("list the markets", ["list"]),
    ],
)
def test_parse_intents(text, intents):
    assert parse(text).intents == intents


def test_parse_prediction_and_unsupported():
    assert parse("Will VOL75 go up over the next hour?").prediction
    assert parse("should I buy VOL10?").prediction
    assert not parse("what does GARCH forecast for vol?").prediction
    assert parse("backtest MACD on VOL75").unsupported[0] == "MACD"


def test_parse_candles_and_lookback():
    req = parse("backtest sma 10/30 on vol 75 using 5-minute candles over the last 2 hours")
    assert req.granularity_s == 300 and req.lookback_s == 7200


# ----------------------------------------------------------------- engine


def ask(market, *turns, symbol="VOL75"):
    history = []
    for i, text in enumerate(turns):
        history.append({"role": "user", "content": text})
        if i < len(turns) - 1:
            history.append({"role": "assistant", "content": "ok"})

    async def collect():
        return [e async for e in local.run_local(market, history, symbol)]

    events = asyncio.run(collect())
    text = "".join(e["delta"] for e in events if e["type"] == "text")
    results = [e for e in events if e["type"] == "tool_result"]
    return events, text, results


@pytest.mark.parametrize(
    "prompt,tools",
    [
        ("Which index is calmest right now?", ["compare_volatility"]),
        ("Did JUMP50 have any jumps recently?", ["volatility_report"]),
        ("Is REGIME calm or turbulent at the moment?", ["detect_regime"]),
        ("What has VOL100 done over the last hour?", ["get_price_summary"]),
        ("Give me a full read on CRASH500: volatility and regimes", ["volatility_report", "detect_regime"]),
        ("Optimise a breakout on VOL50", ["walk_forward_optimize"]),
        ("Run a 2/5 SMA crossover with zero fees on MOMENTUM50 and VOL50", ["run_backtest", "run_backtest"]),
        ("What can I analyse? List the markets.", ["list_symbols"]),
    ],
)
def test_engine_picks_tools(market, prompt, tools):
    events, text, results = ask(market, prompt)
    assert sorted(r["name"] for r in results) == sorted(tools)
    assert all(r["ok"] for r in results)
    assert events[-1] == {"type": "done", "usage": None, "engine": "local"}
    assert text.strip()


def test_engine_finds_planted_edge_and_says_so(market):
    _, text, results = ask(market, "Run a 2/5 SMA crossover with zero fees on MOMENTUM50 and on VOL50")
    assert "only **MOMENTUM50** showed timing better than random" in text
    assert {r["input"]["symbol"] for r in results} == {"MOMENTUM50", "VOL50"}


def test_engine_refuses_to_predict_but_gives_a_range(market):
    _, text, results = ask(market, "Will VOL75 go up over the next hour?")
    assert "can't tell you which way" in text
    assert "typical one-hour move" in text
    assert [r["name"] for r in results] == ["volatility_report"]


def test_engine_declines_unsupported_strategy(market):
    _, text, results = ask(market, "Backtest a MACD strategy on VOL75")
    assert results == []
    assert "isn't in my strategy toolkit" in text and "an SMA crossover" in text


def test_engine_uses_chart_symbol_when_none_given(market):
    _, text, results = ask(market, "what regime is it in?", symbol="REGIME")
    assert results[0]["input"]["symbol"] == "REGIME"
    assert "the index on your chart" in text


def test_follow_up_reuses_strategy_and_symbol(market):
    _, _, results = ask(market, "Backtest a 10/40 SMA crossover on VOL25", "now add a 1% stop-loss")
    args = results[0]["input"]
    assert args["symbol"] == "VOL25"
    assert args["strategy"]["signal"] == {"type": "sma_cross", "fast": 10, "slow": 40}
    assert args["strategy"]["stop_loss_pct"] == 1.0

    _, _, results = ask(market, "Backtest a 10/40 SMA crossover on VOL25", "what about VOL50?")
    assert results[0]["name"] == "run_backtest" and results[0]["input"]["symbol"] == "VOL50"


def test_greeting_after_analysis_is_not_a_follow_up(market):
    _, text, results = ask(market, "Backtest a 20/50 SMA crossover on VOL75", "hello")
    assert results == []
    assert "local analyst" in text


def test_invalid_strategy_is_explained(market):
    _, text, results = ask(market, "backtest a 30-tick breakout on VOL75 with a 80% stop-loss")
    assert results == []
    assert "couldn't build that strategy" in text
