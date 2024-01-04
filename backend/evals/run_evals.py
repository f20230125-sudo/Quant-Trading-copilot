"""Tool-selection eval for the copilot.

Runs each prompt through a copilot engine and checks that the expected tools
were called (and, for a few prompts, that the reply says the right thing).
The Claude engine costs a few model calls per case, so that run spends real
API credit; the local analyst is free.

    cd backend
    .venv/Scripts/python -m evals.run_evals --engine local   # free, offline
    .venv/Scripts/python -m evals.run_evals                  # Claude, all cases
    .venv/Scripts/python -m evals.run_evals --only 3 8       # selected cases
"""

from __future__ import annotations

import argparse
import asyncio
import re
import sys
import time
from dataclasses import dataclass, field

from app.agent.loop import run_agent
from app.config import get_settings
from app.agent import local
from app.agent.client import build_client
from app.market import SyntheticMarket


@dataclass
class Case:
    prompt: str
    expect_all: set[str] = field(default_factory=set)  # every one of these tools must be called
    expect_any: set[str] = field(default_factory=set)  # at least one of these must be called
    reply_must_match: str | None = None  # regex the final text must match (case-insensitive)


CASES = [
    Case("Which index is calmest right now?", expect_all={"compare_volatility"}),
    Case("What's the current volatility of VOL75 compared with its design value?", expect_all={"volatility_report"}),
    Case("Did JUMP50 have any jumps recently? How big?", expect_all={"volatility_report"}),
    Case("Is REGIME calm or turbulent at the moment?", expect_all={"detect_regime"}),
    Case("Does VOL50 have distinct volatility regimes?", expect_all={"detect_regime"}, reply_must_match=r"noise|stable|single|constant"),
    Case("What can I analyse here? List the markets.", expect_all={"list_symbols"}),
    Case("What has VOL100 done over the last hour?", expect_all={"get_price_summary"}),
    Case("Backtest a 20/50 SMA crossover on VOL75.", expect_all={"run_backtest"}),
    Case("Test RSI mean reversion on VOL25 with 30/70 thresholds.", expect_all={"run_backtest"}),
    Case("Try a 50-tick breakout on MOMENTUM50, long only, with a 0.5% stop-loss.", expect_all={"run_backtest"}),
    Case("Optimise an SMA crossover on VOL50.", expect_all={"walk_forward_optimize"}),
    Case("Tune a breakout strategy on MOMENTUM50 and tell me whether it holds up out of sample.", expect_all={"walk_forward_optimize"}),
    Case("Rank VOL10, VOL75 and JUMP50 by current volatility.", expect_all={"compare_volatility"}),
    Case("Run a 2/5 SMA crossover with zero fees on MOMENTUM50 and on VOL50. Which one has a real edge?", expect_all={"run_backtest"}, reply_must_match=r"MOMENTUM50"),
    Case("Give me a full read on CRASH500: volatility and regimes.", expect_all={"volatility_report", "detect_regime"}),
    Case("Backtest SMA 10/30 on VOL75 using 1-minute candles.", expect_all={"run_backtest"}),
    Case("How volatile is STEP compared with VOL10?", expect_any={"compare_volatility", "volatility_report"}),
    Case("Backtest a MACD strategy on VOL75.", reply_must_match=r"(not|n't) (supported|available)|can(not|'t)|closest|instead"),
    Case("Will VOL75 go up over the next hour?", reply_must_match=r"random|can(not|'t) (predict|know)|no (information|edge)|unpredictable"),
    Case("What's the p-value of a 5/20 SMA crossover on VOL100?", expect_all={"run_backtest"}, reply_must_match=r"p\s*[=≈<>]|p-value"),
]


async def run_case(client, settings, market, case: Case, engine: str) -> dict:
    tools: list[str] = []
    text: list[str] = []
    errors: list[str] = []
    usage = None
    started = time.monotonic()
    history = [{"role": "user", "content": case.prompt}]
    events = local.run_local(market, history) if engine == "local" else run_agent(client, settings, market, history)
    async for event in events:
        if event["type"] == "tool_result":
            tools.append(event["name"])
        elif event["type"] == "text":
            text.append(event["delta"])
        elif event["type"] == "error":
            errors.append(event["message"])
        elif event["type"] == "done":
            usage = event["usage"]
    reply = "".join(text)
    called = set(tools)
    passed = (
        not errors
        and case.expect_all <= called
        and (not case.expect_any or bool(case.expect_any & called))
        and (case.reply_must_match is None or re.search(case.reply_must_match, reply, re.I) is not None)
    )
    return {"passed": passed, "tools": tools, "errors": errors, "usage": usage, "seconds": time.monotonic() - started, "reply": reply}


async def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # Windows consoles default to cp1252
    parser = argparse.ArgumentParser()
    parser.add_argument("--only", type=int, nargs="*", help="1-based case numbers to run")
    parser.add_argument("--dry-run", action="store_true", help="list cases without calling the API")
    parser.add_argument("--engine", choices=["claude", "local"], default="claude")
    args = parser.parse_args()

    selected = [(i, c) for i, c in enumerate(CASES, 1) if not args.only or i in args.only]
    if args.dry_run:
        for i, c in selected:
            print(f"{i:2d}. {c.prompt}  ->  all={sorted(c.expect_all)} any={sorted(c.expect_any)} match={c.reply_must_match}")
        return 0

    settings = get_settings()
    client = None
    if args.engine == "claude":
        client = build_client(settings)
        if client is None:
            print("No Anthropic credentials: set ANTHROPIC_API_KEY in backend/.env, or use --engine local", file=sys.stderr)
            return 2
    else:
        local.TYPE_DELAY_S = 0
    market = SyntheticMarket(seed=settings.market_seed, history_size=settings.market_history_size)

    passed = 0
    totals = {"input_tokens": 0, "output_tokens": 0, "cache_read_input_tokens": 0}
    engine = f"{settings.claude_model} (effort {settings.claude_effort})" if args.engine == "claude" else "local analyst"
    print(f"Engine: {engine} · {len(selected)} cases\n")
    for i, case in selected:
        result = await run_case(client, settings, market, case, args.engine)
        passed += result["passed"]
        for k in totals:
            totals[k] += (result["usage"] or {}).get(k, 0)
        mark = "PASS" if result["passed"] else "FAIL"
        print(f"{mark} {i:2d}. {case.prompt[:70]:70s} tools={result['tools']} ({result['seconds']:.0f}s)")
        if not result["passed"]:
            detail = result["errors"] or [result["reply"][:300].replace("\n", " ")]
            print(f"         {detail[0]}")

    print(f"\n{passed}/{len(selected)} passed · tokens in {totals['input_tokens']:,} "
          f"(cached {totals['cache_read_input_tokens']:,}) · out {totals['output_tokens']:,}")
    return 0 if passed == len(selected) else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
