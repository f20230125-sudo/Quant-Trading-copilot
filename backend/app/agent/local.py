"""The local analyst: a no-API-key copilot engine.

Parses the question with rules (parse.py), runs the same tools the Claude
agent uses, and writes the answer from the results (narrate.py). It emits the
same event stream as the Claude loop, so the UI renders both identically.
It follows up on earlier turns: "now add a 1% stop" reuses the last strategy
and symbol.
"""

from __future__ import annotations

import asyncio
import json
import re
import time
from collections.abc import AsyncIterator
from typing import Any

from pydantic import ValidationError

from ..market import SyntheticMarket, UnknownSymbolError
from ..quant.strategies import StrategySpec
from . import narrate
from .parse import Request, parse
from .tools import execute_tool

MAX_SYMBOLS = 12
TYPE_DELAY_S = 0.012
FOLLOW_UP = re.compile(r"^\s*(now|then|and|also|what about|how about|try|same|again|instead|ok|okay|and now|with)\b", re.I)


def _chunks(text: str, words: int = 3) -> list[str]:
    tokens = re.findall(r"\S+\s*|\s+", text)
    return ["".join(tokens[i : i + words]) for i in range(0, len(tokens), words)]


def _ticks(market: SyntheticMarket, symbol: str, seconds: int, lo: int, hi: int = 20_000) -> int:
    interval = market.feed(symbol).spec.interval_s
    return max(lo, min(hi, seconds // interval))


class Planner:
    """Turns the latest message (plus earlier ones, for follow-ups) into tool calls."""

    def __init__(self, market: SyntheticMarket, history: list[dict[str, Any]], context_symbol: str | None):
        self.market = market
        users = [m["content"] for m in history if m["role"] == "user"]
        self.req = parse(users[-1])
        self.previous = [parse(text) for text in reversed(users[:-1][-6:])]
        self.context_symbol = context_symbol
        self.notes: list[str] = []
        # A follow-up either says so ("now...", "what about...") or only changes a detail
        # (a new symbol, a stop-loss) without asking a new kind of question.
        changes_detail = not self.req.intents and bool(self.req.symbols or self.req.strategy)
        self.is_follow_up = bool(self.previous) and (bool(FOLLOW_UP.search(users[-1])) or changes_detail)

    def _valid(self, symbols: list[str]) -> list[str]:
        out = []
        for s in symbols:
            try:
                out.append(self.market.feed(s).spec.symbol)
            except UnknownSymbolError:
                continue
        return out

    def symbols(self) -> list[str]:
        req = self.req
        if req.all_symbols:
            return [row["symbol"] for row in self.market.symbols()]
        if req.symbols:
            return self._valid(req.symbols)[:MAX_SYMBOLS]
        if self.is_follow_up:
            for prev in self.previous:
                if prev.symbols:
                    return self._valid(prev.symbols)[:MAX_SYMBOLS]
        if self.context_symbol:
            valid = self._valid([self.context_symbol])
            if valid:
                self.notes.append(f"using **{valid[0]}**, the index on your chart")
                return valid
        return ["VOL75"]

    def intents(self) -> list[str]:
        if self.req.intents:
            return list(self.req.intents)
        if self.is_follow_up:
            for prev in self.previous:
                if prev.intents:
                    return list(prev.intents)
        if self.req.prediction:
            return ["volatility"]
        if self.req.symbols:
            return ["volatility", "regime"]  # a bare symbol: give a general read
        return []

    def strategy(self) -> dict[str, Any]:
        req = self.req
        if req.strategy_explicit:
            return dict(req.strategy or {})
        for prev in self.previous:
            if prev.strategy_explicit and prev.strategy:
                # Follow-up: keep the earlier strategy, apply this message's modifiers.
                return {**prev.strategy, **(req.strategy or {})}
        self.notes.append("no strategy given, so I used a 20/50 SMA crossover")
        return {"signal": {"type": "sma_cross", "fast": 20, "slow": 50}, **(req.strategy or {})}

    def plan(self) -> tuple[list[tuple[str, dict[str, Any]]], dict[str, Any] | None]:
        req = self.req
        if req.help and not req.symbols:
            return [], None
        intents = self.intents()
        if req.prediction and "volatility" not in intents:
            intents.append("volatility")
        if req.unsupported and not req.strategy_explicit:
            intents = [i for i in intents if i not in ("backtest", "walk_forward")]
        if not intents:
            return [], None

        per_symbol = {"prices", "volatility", "regime", "backtest", "walk_forward"}
        needs_symbol = bool(per_symbol & set(intents)) or ("compare" in intents and len(req.symbols) >= 2)
        symbols = self.symbols() if needs_symbol else []
        spec = None
        if "backtest" in intents or "walk_forward" in intents:
            spec = self.strategy()
        extra: dict[str, Any] = {}
        if req.granularity_s:
            extra["granularity_s"] = req.granularity_s

        calls: list[tuple[str, dict[str, Any]]] = []
        if "list" in intents:
            calls.append(("list_symbols", {}))
        if "compare" in intents:
            calls.append(("compare_volatility", {"symbols": symbols} if len(req.symbols) >= 2 else {}))
        for sym in symbols:
            if "prices" in intents:
                count = req.count or (_ticks(self.market, sym, req.lookback_s or 3600, 10) if not req.granularity_s else 120)
                calls.append(("get_price_summary", {"symbol": sym, "count": count, **extra}))
            if "volatility" in intents and "compare" not in intents:
                args = {"symbol": sym}
                if req.lookback_s or req.count:
                    args["count"] = req.count or _ticks(self.market, sym, req.lookback_s, 200)
                calls.append(("volatility_report", args))
            if "regime" in intents:
                args = {"symbol": sym}
                if req.lookback_s or req.count:
                    args["count"] = req.count or _ticks(self.market, sym, req.lookback_s, 500)
                calls.append(("detect_regime", args))
            if "backtest" in intents:
                args = {"symbol": sym, "strategy": spec, **extra}
                if req.count:
                    args["count"] = req.count
                calls.append(("run_backtest", args))
            if "walk_forward" in intents:
                calls.append(("walk_forward_optimize", {"symbol": sym, "strategy": spec, **extra}))
        return calls, spec


def _intro(calls: list[tuple[str, dict[str, Any]]], spec: dict[str, Any] | None, notes: list[str]) -> str:
    verbs = {
        "list_symbols": "listing the indices",
        "compare_volatility": "ranking volatility",
        "get_price_summary": "summarising price action",
        "volatility_report": "measuring volatility",
        "detect_regime": "checking for regimes",
        "run_backtest": "backtesting",
        "walk_forward_optimize": "running a walk-forward optimisation",
    }
    seen: list[str] = []
    for name, _ in calls:
        if verbs[name] not in seen:
            seen.append(verbs[name])
    action = ", ".join(seen[:-1]) + (" and " if len(seen) > 1 else "") + seen[-1]
    symbols = list(dict.fromkeys(a["symbol"] for _, a in calls if "symbol" in a))
    target = f" on {', '.join(f'**{s}**' for s in symbols[:4])}" if symbols else ""
    label = narrate.strategy_label(spec) if spec else ""
    strategy = f" with {narrate.article(label)} {label}" if spec else ""
    note = f" ({'; '.join(notes)})" if notes else ""
    return f"{action[0].upper()}{action[1:]}{target}{strategy}{note}.\n\n"


async def run_local(
    market: SyntheticMarket, history: list[dict[str, Any]], context_symbol: str | None = None
) -> AsyncIterator[dict[str, Any]]:
    planner = Planner(market, history, context_symbol)
    req: Request = planner.req
    calls, spec = planner.plan()

    if spec is not None:
        try:
            spec = StrategySpec.model_validate(spec).model_dump()
        except ValidationError as exc:
            message = "; ".join(e["msg"] for e in exc.errors(include_url=False))
            async for event in _type(f"I couldn't build that strategy: {message}. " + narrate.HELP.split("\n\n")[-1]):
                yield event
            yield {"type": "done", "usage": None, "engine": "local"}
            return
        calls = [(n, {**a, "strategy": spec} if "strategy" in a else a) for n, a in calls]

    sections: list[str] = []
    if req.unsupported and not req.strategy_explicit:
        name, closest, example = req.unsupported
        sections.append(narrate.unsupported(name, closest, example, (req.symbols or [context_symbol or "VOL75"])[0]))
    if req.prediction:
        sections.append(narrate.PREDICTION_PREFACE)

    if not calls:
        if not sections:
            sections.append(narrate.HELP)
        async for event in _type("\n\n".join(sections)):
            yield event
        yield {"type": "done", "usage": None, "engine": "local"}
        return

    async for event in _type(_intro(calls, spec, planner.notes)):
        yield event

    ids = [f"local_{i}" for i in range(len(calls))]
    for (name, _), tool_id in zip(calls, ids, strict=True):
        yield {"type": "tool_start", "id": tool_id, "name": name}

    async def run(i: int) -> tuple[int, Any]:
        name, args = calls[i]
        return i, await execute_tool(market, name, args)

    results: dict[int, Any] = {}
    for next_done in asyncio.as_completed([run(i) for i in range(len(calls))]):
        i, result = await next_done
        results[i] = result
        name, args = calls[i]
        yield {
            "type": "tool_result",
            "id": ids[i],
            "name": name,
            "input": args,
            "ok": not result.is_error,
            "error": json.loads(result.content).get("error") if result.is_error else None,
            "ui": result.ui,
        }

    now = int(time.time())
    for i, (name, args) in enumerate(calls):
        result = results[i]
        data = json.loads(result.content)
        if result.is_error:
            sections.append(f"*{name.replace('_', ' ').capitalize()} failed: {data['error']}*")
        elif name == "list_symbols":
            sections.append(narrate.symbols(data))
        elif name == "compare_volatility":
            sections.append(narrate.compare(data))
        elif name == "get_price_summary":
            sections.append(narrate.prices(data))
        elif name == "volatility_report":
            sections.append(narrate.volatility(data, now))
            if req.prediction:
                _, last = market.history(args["symbol"], 1)
                estimate = (data.get("garch") or {}).get("forecast_vol") or data["realized_vol"]
                sections.append(narrate.one_hour_range(estimate, float(last[-1])))
        elif name == "detect_regime":
            sections.append(narrate.regime(data))
        elif name == "run_backtest":
            sections.append(narrate.backtest(data, args["strategy"]))
        elif name == "walk_forward_optimize":
            sections.append(narrate.walk_forward(data, args["strategy"]))

    backtests = [json.loads(results[i].content) for i, (n, _) in enumerate(calls) if n == "run_backtest" and not results[i].is_error]
    if len(backtests) > 1:
        edges = [b["symbol"] for b in backtests if b["null_test"]["p_value"] < 0.05]
        sections.append(
            f"**Across the {len(backtests)} runs:** "
            + (f"only {', '.join(f'**{s}**' for s in edges)} showed timing better than random." if edges else "none showed timing better than random.")
        )

    async for event in _type("\n\n".join(sections)):
        yield event
    yield {"type": "done", "usage": None, "engine": "local"}


async def _type(text: str) -> AsyncIterator[dict[str, Any]]:
    """Stream text in small chunks so replies appear progressively, like the Claude engine's."""
    for chunk in _chunks(text):
        yield {"type": "text", "delta": chunk}
        await asyncio.sleep(TYPE_DELAY_S)
