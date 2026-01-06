import asyncio
import json
from types import SimpleNamespace as NS

import pytest

from app.agent.loop import request_params, run_agent
from app.agent.tools import TOOLS, execute_tool, tool_definitions
from app.config import Settings
from app.market import SyntheticMarket

NOW = 1_800_000_000


@pytest.fixture(scope="module")
def market():
    return SyntheticMarket(seed=1, history_size=20_000, now=NOW)


def run(coro):
    return asyncio.run(coro)


# ----------------------------------------------------------------- tool schemas

def test_tool_schemas_are_self_contained():
    defs = tool_definitions()
    assert {d["name"] for d in defs} == set(TOOLS)
    for d in defs:
        text = json.dumps(d["input_schema"])
        assert "$ref" not in text and "$defs" not in text
        assert d["input_schema"]["type"] == "object"
        assert d["description"]
    backtest = next(d for d in defs if d["name"] == "run_backtest")
    variants = backtest["input_schema"]["properties"]["strategy"]["properties"]["signal"]["oneOf"]
    assert {v["properties"]["type"]["const"] for v in variants} == {"sma_cross", "rsi", "breakout"}


# ----------------------------------------------------------------- tool execution

@pytest.mark.parametrize(
    "name,args,kind",
    [
        ("list_symbols", {}, "symbols"),
        ("get_price_summary", {"symbol": "VOL75", "count": 300}, "prices"),
        ("get_price_summary", {"symbol": "VOL75", "count": 100, "granularity_s": 60}, "prices"),
        ("volatility_report", {"symbol": "JUMP50"}, "volatility"),
        ("detect_regime", {"symbol": "REGIME"}, "regime"),
        ("compare_volatility", {"symbols": ["VOL10", "VOL100"]}, "compare"),
        ("run_backtest", {"symbol": "VOL50", "strategy": {"signal": {"type": "rsi"}}}, "backtest"),
        ("walk_forward_optimize", {"symbol": "VOL50", "strategy": {"signal": {"type": "breakout", "lookback": 20}}}, "walk_forward"),
    ],
)
def test_every_tool_runs(market, name, args, kind):
    result = run(execute_tool(market, name, args))
    assert not result.is_error, result.content
    assert result.ui["kind"] == kind
    payload = json.loads(result.content)  # valid JSON for the model
    assert "_curves" not in payload and "_rolling" not in payload


def test_compare_sorts_calmest_first(market):
    result = run(execute_tool(market, "compare_volatility", {}))
    rows = json.loads(result.content)["sorted_calmest_first"]
    assert len(rows) == 12
    vols = [r["current_vol"] for r in rows]
    assert vols == sorted(vols)
    order = [r["symbol"] for r in rows]
    assert order.index("VOL10") < order.index("VOL50") < order.index("VOL100")


@pytest.mark.parametrize(
    "name,args,fragment",
    [
        ("run_backtest", {"symbol": "VOL75", "strategy": {"signal": {"type": "macd"}}}, "Invalid input"),
        ("volatility_report", {"symbol": "VOL57"}, "Did you mean"),
        ("run_backtest", {"symbol": "VOL75", "count": 200, "strategy": {"signal": {"type": "sma_cross", "fast": 50, "slow": 400}}}, "Not enough data"),
        ("delete_everything", {}, "Unknown tool"),
    ],
)
def test_bad_calls_become_recoverable_errors(market, name, args, fragment):
    result = run(execute_tool(market, name, args))
    assert result.is_error
    assert fragment in result.content


# ----------------------------------------------------------------- request params

def test_request_params_per_model():
    opus = request_params(Settings(claude_model="claude-opus-5", claude_effort="medium"))
    assert opus["fallbacks"] == "default" and opus["betas"] == ["server-side-fallback-2026-07-01"]
    assert opus["output_config"] == {"effort": "medium"}
    sonnet = request_params(Settings(claude_model="claude-sonnet-5"))
    assert "fallbacks" not in sonnet and "betas" not in sonnet
    assert "output_config" not in request_params(Settings(claude_model="claude-haiku-4-5"))


# ----------------------------------------------------------------- loop with a scripted client

class FakeStream:
    def __init__(self, events, final):
        self.events, self.final = events, final

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def _iter(self):
        for event in self.events:
            yield event

    def __aiter__(self):
        return self._iter()

    async def get_final_message(self):
        return self.final


class FakeClient:
    def __init__(self, streams):
        self.streams = list(streams)
        self.requests = []
        self.beta = NS(messages=NS(stream=self._stream))

    def _stream(self, **kwargs):
        self.requests.append({**kwargs, "messages": list(kwargs["messages"])})
        return self.streams.pop(0)


def usage():
    return NS(input_tokens=100, output_tokens=20, cache_read_input_tokens=50)


def tool_turn(*calls):
    blocks = [NS(type="tool_use", id=f"t{i}", name=name, input=args) for i, (name, args) in enumerate(calls)]
    events = [NS(type="content_block_start", content_block=b) for b in blocks]
    return FakeStream(events, NS(stop_reason="tool_use", content=blocks, usage=usage()))


def text_turn(text):
    return FakeStream([NS(type="text", text=text)], NS(stop_reason="end_turn", content=[NS(type="text", text=text)], usage=usage()))


async def collect(client, market, settings=None):
    settings = settings or Settings(claude_model="claude-sonnet-5")
    history = [{"role": "user", "content": "Which is calmer, VOL10 or VOL100? Also check the regime on REGIME."}]
    return [e async for e in run_agent(client, settings, market, history)]


def test_loop_runs_parallel_tools_then_answers(market):
    client = FakeClient(
        [
            tool_turn(("compare_volatility", {"symbols": ["VOL10", "VOL100"]}), ("detect_regime", {"symbol": "REGIME"})),
            text_turn("VOL10 is calmer."),
        ]
    )
    events = run(collect(client, market))
    types = [e["type"] for e in events]
    assert types == ["tool_start", "tool_start", "tool_result", "tool_result", "text", "done"]
    assert events[-1]["usage"]["requests"] == 2 and events[-1]["usage"]["cache_read_input_tokens"] == 100

    # Both results were returned together, in one user message, matched by id.
    followup = client.requests[1]["messages"][-1]
    assert followup["role"] == "user"
    assert [b["tool_use_id"] for b in followup["content"]] == ["t0", "t1"]


def test_loop_feeds_tool_errors_back(market):
    client = FakeClient(
        [tool_turn(("volatility_report", {"symbol": "NOPE"})), text_turn("That symbol doesn't exist.")]
    )
    events = run(collect(client, market))
    result = next(e for e in events if e["type"] == "tool_result")
    assert result["ok"] is False and "Unknown symbol" in result["error"]
    assert client.requests[1]["messages"][-1]["content"][0]["is_error"] is True


def test_loop_stops_at_iteration_cap(market):
    settings = Settings(claude_model="claude-sonnet-5", max_agent_iterations=2)
    client = FakeClient([tool_turn(("list_symbols", {})), tool_turn(("list_symbols", {}))])
    events = run(collect(client, market, settings))
    assert "Stopped after 2 rounds" in "".join(e.get("delta", "") for e in events)
    assert events[-1]["type"] == "done"
