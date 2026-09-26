from __future__ import annotations

import json
import logging
from typing import Literal, Self

import anthropic
import numpy as np
from fastapi import APIRouter, HTTPException, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, model_validator

from ..agent import client as claude_client
from ..agent.local import run_local
from ..agent.loop import run_agent
from ..market import SyntheticMarket, UnknownSymbolError
from ..quant.volatility import log_returns, periods_per_year, realized_vol

log = logging.getLogger(__name__)
router = APIRouter()

SNAPSHOT_WINDOW_S = 1800
SPARK_POINTS = 60


def _market(request: Request) -> SyntheticMarket:
    return request.app.state.market


@router.get("/api/health")
async def health(request: Request):
    settings = request.app.state.settings
    claude_ready = request.app.state.anthropic is not None
    return {
        "status": "ok",
        "copilot_ready": True,  # the local analyst always works
        "claude_ready": claude_ready,
        "default_engine": "claude" if claude_ready else "local",
        "model": settings.claude_model,
        "symbols": len(_market(request).symbols()),
    }


@router.get("/api/symbols")
async def symbols(request: Request):
    return _market(request).symbols()


@router.get("/api/snapshot")
async def snapshot(request: Request):
    """Every index's last price, 30-minute change, realized vol and a sparkline, for the watchlist."""
    market = _market(request)
    rows = []
    for info in market.symbols():
        epochs, prices = market.history(info["symbol"], SNAPSHOT_WINDOW_S // info["tick_interval_s"])
        step = max(1, len(prices) // SPARK_POINTS)
        spark = np.append(prices[::step], prices[-1])
        rows.append(
            {
                "symbol": info["symbol"],
                "name": info["name"],
                "category": info["category"],
                "decimals": info["decimals"],
                "design_vol": info["design_vol"],
                "last": round(float(prices[-1]), info["decimals"]),
                "change_pct": float(prices[-1] / prices[0] - 1),
                "realized_vol": realized_vol(log_returns(prices), periods_per_year(epochs)),
                "spark": [round(float(p), info["decimals"] + 2) for p in spark],
            }
        )
    return {"window_minutes": SNAPSHOT_WINDOW_S // 60, "rows": rows}


@router.get("/api/history/{symbol}")
async def history(
    request: Request,
    symbol: str,
    count: int = Query(1000, ge=10, le=5000),
    granularity: int = Query(0, ge=0, le=86_400, description="0 = ticks, else candle seconds"),
):
    market = _market(request)
    try:
        spec = market.feed(symbol).spec
        if granularity:
            candles = market.candles(symbol, granularity, count)
            points = [
                {"t": c["epoch"], "o": c["open"], "h": c["high"], "l": c["low"], "c": c["close"]} for c in candles
            ]
        else:
            epochs, prices = market.history(symbol, count)
            points = [{"t": int(t), "v": round(float(p), spec.decimals)} for t, p in zip(epochs, prices, strict=True)]
    except UnknownSymbolError as exc:
        raise HTTPException(404, str(exc)) from exc
    return {"symbol": spec.symbol, "decimals": spec.decimals, "granularity": granularity, "points": points}


@router.websocket("/ws/ticks/{symbol}")
async def ticks(ws: WebSocket, symbol: str):
    await ws.accept()
    market: SyntheticMarket = ws.app.state.market
    try:
        async with market.listen(symbol) as queue:
            while True:
                await ws.send_json(await queue.get())
    except UnknownSymbolError as exc:
        await ws.send_json({"type": "error", "message": str(exc)})
        await ws.close(code=1008)
    except (WebSocketDisconnect, RuntimeError):
        pass  # client went away


# ---------------------------------------------------------------- Claude key


class KeyRequest(BaseModel):
    api_key: str = Field(min_length=20, max_length=300, pattern=r"^\S+$")
    remember: bool = False


@router.post("/api/copilot/key")
async def connect_claude(body: KeyRequest, request: Request):
    """Verify an Anthropic API key and switch the copilot to Claude. The key never leaves the backend."""
    state = request.app.state
    if not state.key_limiter.allow(request.client.host if request.client else "unknown"):
        raise HTTPException(429, "Too many attempts. Please wait a minute.")
    try:
        client = await claude_client.verify_key(body.api_key.strip())
    except anthropic.AuthenticationError as exc:
        raise HTTPException(401, "Anthropic rejected that key. Check it and try again.") from exc
    except anthropic.PermissionDeniedError as exc:
        raise HTTPException(403, "That key doesn't have permission to use the API.") from exc
    except anthropic.APIConnectionError as exc:
        raise HTTPException(502, "Couldn't reach the Anthropic API to verify the key.") from exc
    except anthropic.APIStatusError as exc:
        raise HTTPException(502, f"Anthropic API error ({exc.status_code}) while verifying the key.") from exc
    state.anthropic = client
    if body.remember:
        claude_client.save_key(body.api_key.strip())
    return {"claude_ready": True, "saved": body.remember}


@router.delete("/api/copilot/key")
async def disconnect_claude(request: Request):
    """Stop using Claude for this session. A key saved in backend/.env is left in place."""
    request.app.state.anthropic = None
    return {"claude_ready": False}


# ---------------------------------------------------------------- chat


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(max_length=8000)


class ChatContext(BaseModel):
    symbol: str | None = Field(None, max_length=20)


class ChatRequest(BaseModel):
    messages: list[ChatMessage] = Field(min_length=1, max_length=40)
    engine: Literal["auto", "local", "claude"] = "auto"
    context: ChatContext | None = None

    @model_validator(mode="after")
    def _ends_with_user(self) -> Self:
        if self.messages[-1].role != "user" or not self.messages[-1].content.strip():
            raise ValueError("the last message must be a non-empty user message")
        return self


def _sse(events):
    async def stream():
        try:
            async for event in events:
                yield f"data: {json.dumps(event)}\n\n"
        except Exception:
            log.exception("chat stream failed")
            yield f"data: {json.dumps({'type': 'error', 'message': 'Internal error while generating a reply.'})}\n\n"
            yield f"data: {json.dumps({'type': 'done', 'usage': None})}\n\n"

    return StreamingResponse(
        stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
    )


@router.post("/api/chat")
async def chat(body: ChatRequest, request: Request):
    state = request.app.state
    # Empty assistant turns (e.g. a reply that was only tool cards) are rejected by the API.
    history = [m.model_dump() for m in body.messages if m.content.strip()]
    while history and history[0]["role"] != "user":
        history.pop(0)
    symbol = body.context.symbol if body.context else None

    use_claude = body.engine == "claude" or (body.engine == "auto" and state.anthropic is not None)
    if not use_claude:
        return _sse(run_local(state.market, history, symbol))

    if state.anthropic is None:
        raise HTTPException(503, "Claude isn't connected. Add an API key in the copilot panel, or use the local analyst.")
    if not state.chat_limiter.allow(request.client.host if request.client else "unknown"):
        raise HTTPException(429, "Too many requests. Please wait a minute.")
    if symbol:
        last = history[-1]
        history[-1] = {**last, "content": f"(The chart is showing {symbol}.)\n\n{last['content']}"}
    return _sse(run_agent(state.anthropic, state.settings, state.market, history))
