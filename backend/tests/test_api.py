import json
import time

import pytest
from fastapi.testclient import TestClient

from app.api.ratelimit import SlidingWindowLimiter
from app.config import Settings
from app.main import create_app
from app.market import SyntheticMarket

from .test_agent import FakeClient, text_turn


@pytest.fixture
def client():
    market = SyntheticMarket(seed=3, history_size=3000, now=int(time.time()))
    app = create_app(Settings(chat_rate_limit_per_minute=3), market=market)
    app.state.anthropic = None  # never call the real API from tests
    with TestClient(app) as c:
        yield c


def test_health_and_symbols(client):
    assert client.get("/api/health").json()["symbols"] == 12
    symbols = client.get("/api/symbols").json()
    assert {s["symbol"] for s in symbols} >= {"VOL75", "STEP", "MOMENTUM50"}


def test_history_ticks_and_candles(client):
    ticks = client.get("/api/history/VOL75?count=100").json()
    assert len(ticks["points"]) == 100 and ticks["decimals"] == 2
    candles = client.get("/api/history/VOL75?count=10&granularity=60").json()
    assert set(candles["points"][0]) == {"t", "o", "h", "l", "c"}
    assert client.get("/api/history/NOPE").status_code == 404


def test_live_ticks_over_websocket(client):
    with client.websocket_connect("/ws/ticks/STEP") as ws:
        first, second = ws.receive_json(), ws.receive_json()
    assert first["type"] == "tick" and second["epoch"] > first["epoch"]
    assert round(abs(second["quote"] - first["quote"]), 6) == 0.1 or second["epoch"] - first["epoch"] > 1


def test_websocket_unknown_symbol(client):
    with client.websocket_connect("/ws/ticks/NOPE") as ws:
        assert ws.receive_json()["type"] == "error"


def test_chat_without_key_uses_local_analyst(client, monkeypatch):
    import app.agent.local as local

    monkeypatch.setattr(local, "TYPE_DELAY_S", 0)
    res = client.post(
        "/api/chat",
        json={"messages": [{"role": "user", "content": "how volatile is vol 75?"}], "context": {"symbol": "VOL75"}},
    )
    assert res.status_code == 200
    events = [json.loads(line[6:]) for line in res.text.splitlines() if line.startswith("data: ")]
    assert any(e["type"] == "tool_result" and e["name"] == "volatility_report" for e in events)
    assert events[-1]["engine"] == "local"
    health = client.get("/api/health").json()
    assert health["copilot_ready"] and not health["claude_ready"] and health["default_engine"] == "local"


def test_chat_explicit_claude_without_key(client):
    res = client.post("/api/chat", json={"messages": [{"role": "user", "content": "hi"}], "engine": "claude"})
    assert res.status_code == 503


def test_chat_validates_body(client):
    assert client.post("/api/chat", json={"messages": []}).status_code == 422
    assert client.post("/api/chat", json={"messages": [{"role": "assistant", "content": "x"}]}).status_code == 422
    assert client.post("/api/chat", json={"messages": [{"role": "system", "content": "x"}]}).status_code == 422
    assert client.post("/api/chat", json={"messages": [{"role": "user", "content": "x"}], "engine": "gpt"}).status_code == 422


def test_chat_streams_claude_with_chart_context(client):
    client.app.state.anthropic = FakeClient([text_turn("Hello from the copilot.")])
    res = client.post(
        "/api/chat",
        json={
            "messages": [{"role": "assistant", "content": "stale"}, {"role": "user", "content": "hi"}],
            "context": {"symbol": "JUMP50"},
        },
    )
    assert res.headers["content-type"].startswith("text/event-stream")
    events = [json.loads(line[6:]) for line in res.text.splitlines() if line.startswith("data: ")]
    assert [e["type"] for e in events] == ["text", "done"] and events[-1]["engine"] == "claude"
    sent = client.app.state.anthropic.requests[0]["messages"]
    # A leading assistant message is dropped so the conversation starts with the user,
    # and the chart's symbol is passed along as context.
    assert sent[0]["role"] == "user" and sent[0]["content"].startswith("(The chart is showing JUMP50.)")


def test_chat_rate_limit_applies_to_claude(client):
    client.app.state.anthropic = FakeClient([text_turn("ok") for _ in range(3)])
    body = {"messages": [{"role": "user", "content": "hi"}], "engine": "claude"}
    statuses = [client.post("/api/chat", json=body).status_code for _ in range(4)]
    assert statuses == [200, 200, 200, 429]


def test_connect_claude_key(client, monkeypatch):
    import anthropic
    import httpx2

    import app.agent.client as claude_client

    fake = FakeClient([])
    saved = []

    async def ok(key):
        return fake

    async def rejected(key):
        response = httpx2.Response(401, request=httpx2.Request("GET", "https://api.anthropic.com/v1/models"))
        raise anthropic.AuthenticationError("invalid x-api-key", response=response, body=None)

    monkeypatch.setattr(claude_client, "save_key", lambda key: saved.append(key))
    monkeypatch.setattr(claude_client, "verify_key", rejected)
    res = client.post("/api/copilot/key", json={"api_key": "sk-ant-" + "x" * 30})
    assert res.status_code == 401 and client.app.state.anthropic is None

    monkeypatch.setattr(claude_client, "verify_key", ok)
    res = client.post("/api/copilot/key", json={"api_key": "sk-ant-" + "y" * 30, "remember": True})
    assert res.json() == {"claude_ready": True, "saved": True}
    assert client.app.state.anthropic is fake and saved == ["sk-ant-" + "y" * 30]
    assert client.get("/api/health").json()["default_engine"] == "claude"

    assert client.delete("/api/copilot/key").json() == {"claude_ready": False}
    assert client.app.state.anthropic is None
    assert client.post("/api/copilot/key", json={"api_key": "short"}).status_code == 422


def test_save_key_replaces_existing_entry(tmp_path):
    from app.agent.client import save_key

    env = tmp_path / ".env"
    env.write_text("COPILOT_MARKET_SEED=7\nANTHROPIC_API_KEY=old\n", encoding="utf-8")
    save_key("sk-new", env)
    assert env.read_text(encoding="utf-8") == "COPILOT_MARKET_SEED=7\nANTHROPIC_API_KEY=sk-new\n"
    fresh = tmp_path / "fresh.env"
    save_key("sk-a", fresh)
    assert fresh.read_text(encoding="utf-8") == "ANTHROPIC_API_KEY=sk-a\n"


def test_snapshot(client):
    snap = client.get("/api/snapshot").json()
    assert snap["window_minutes"] == 30 and len(snap["rows"]) == 12
    row = next(r for r in snap["rows"] if r["symbol"] == "VOL75")
    assert 20 <= len(row["spark"]) <= 62
    assert abs(row["last"] - row["spark"][-1]) < 0.01
    assert 0.3 < row["realized_vol"] < 1.5


def test_limiter_window_slides():
    limiter = SlidingWindowLimiter(2, window_s=10)
    assert limiter.allow("a", now=0) and limiter.allow("a", now=1)
    assert not limiter.allow("a", now=5)
    assert limiter.allow("a", now=10.5)
    assert limiter.allow("b", now=5)
