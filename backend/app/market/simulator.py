"""In-process synthetic market.

Every index is backfilled with ``history_size`` ticks ending at start-up time,
then a single clock task appends new ticks in real time at each index's own
interval and pushes them to any live listeners. Everything is seeded, so a
given seed and start time always produce the same history.
"""

from __future__ import annotations

import asyncio
import contextlib
import difflib
import itertools
import time
from collections import deque
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

import numpy as np

from .models import GBM, AR1Momentum, CrashBoom, JumpDiffusion, PriceModel, RegimeSwitching, StepModel

LISTENER_QUEUE_SIZE = 256


@dataclass(frozen=True)
class IndexSpec:
    symbol: str
    name: str
    category: str
    interval_s: int
    start_price: float
    decimals: int
    description: str
    design_vol: float | None = None  # annualised; None where volatility isn't a model parameter

    def build_model(self) -> PriceModel:
        return _MODEL_FACTORIES[self.symbol](self.interval_s)


CATALOG: tuple[IndexSpec, ...] = (
    IndexSpec("VOL10", "Volatility 10 Index", "volatility", 2, 6000.0, 3, "Random walk with constant 10% annualised volatility.", 0.1),
    IndexSpec("VOL25", "Volatility 25 Index", "volatility", 2, 2500.0, 3, "Random walk with constant 25% annualised volatility.", 0.25),
    IndexSpec("VOL50", "Volatility 50 Index", "volatility", 2, 300.0, 4, "Random walk with constant 50% annualised volatility.", 0.5),
    IndexSpec("VOL75", "Volatility 75 Index", "volatility", 2, 40000.0, 2, "Random walk with constant 75% annualised volatility.", 0.75),
    IndexSpec("VOL100", "Volatility 100 Index", "volatility", 2, 1500.0, 2, "Random walk with constant 100% annualised volatility.", 1.0),
    IndexSpec("VOL100_1S", "Volatility 100 (1s) Index", "volatility", 1, 900.0, 2, "Random walk with constant 100% annualised volatility, ticking every second.", 1.0),
    IndexSpec("JUMP50", "Jump 50 Index", "jump", 2, 1200.0, 2, "50% volatility random walk with about 3 sudden jumps per hour, each around 30x a normal tick.", 0.5),
    IndexSpec("CRASH500", "Crash 500 Index", "crash_boom", 1, 5000.0, 3, "Drifts upward, with a sharp crash on average once every 500 ticks."),
    IndexSpec("BOOM500", "Boom 500 Index", "crash_boom", 1, 5000.0, 3, "Drifts downward, with a sharp spike on average once every 500 ticks."),
    IndexSpec("STEP", "Step Index", "step", 1, 8000.0, 1, "Moves exactly 0.1 up or down on every tick."),
    IndexSpec("REGIME", "Regime Switch Index", "regime", 2, 1000.0, 2, "Switches between calm (20%) and turbulent (90%) volatility regimes, each lasting about 15 minutes on average."),
    IndexSpec("MOMENTUM50", "Momentum 50 Index", "momentum", 2, 750.0, 3, "50% volatility index whose tick returns show persistent short-term trends.", 0.5),
)

_MODEL_FACTORIES = {
    "VOL10": lambda dt: GBM(0.10, dt),
    "VOL25": lambda dt: GBM(0.25, dt),
    "VOL50": lambda dt: GBM(0.50, dt),
    "VOL75": lambda dt: GBM(0.75, dt),
    "VOL100": lambda dt: GBM(1.00, dt),
    "VOL100_1S": lambda dt: GBM(1.00, dt),
    "JUMP50": lambda dt: JumpDiffusion(0.50, dt),
    "CRASH500": lambda dt: CrashBoom(direction=-1, avg_ticks_between=500),
    "BOOM500": lambda dt: CrashBoom(direction=+1, avg_ticks_between=500),
    "STEP": lambda dt: StepModel(0.1),
    "REGIME": lambda dt: RegimeSwitching((0.20, 0.90), mean_regime_s=900, interval_s=dt),
    "MOMENTUM50": lambda dt: AR1Momentum(0.50, dt, phi=0.15),
}


class UnknownSymbolError(KeyError):
    def __init__(self, symbol: str, suggestions: list[str]):
        super().__init__(symbol)
        self.symbol = symbol
        self.suggestions = suggestions

    def __str__(self) -> str:
        hint = f" Did you mean {', '.join(self.suggestions)}?" if self.suggestions else ""
        return f"Unknown symbol '{self.symbol}'.{hint}"


class Feed:
    """One index: its model, its tick history, and its live listeners."""

    def __init__(self, spec: IndexSpec, rng: np.random.Generator, history_size: int, now: int):
        self.spec = spec
        self._model = spec.build_model()
        self._rng = rng
        prices = self._model.generate(spec.start_price, history_size, rng)
        epochs = now - spec.interval_s * np.arange(history_size - 1, -1, -1)
        self.epochs: deque[int] = deque(epochs.tolist(), maxlen=history_size)
        self.prices: deque[float] = deque(prices.tolist(), maxlen=history_size)
        self.listeners: set[asyncio.Queue[dict[str, Any]]] = set()

    @property
    def last_epoch(self) -> int:
        return self.epochs[-1]

    def advance(self, epoch: int) -> dict[str, Any]:
        price = float(self._model.generate(self.prices[-1], 1, self._rng)[0])
        self.epochs.append(epoch)
        self.prices.append(price)
        tick = {"type": "tick", "epoch": epoch, "quote": round(price, self.spec.decimals)}
        for queue in list(self.listeners):
            if queue.full():  # slow consumer: drop its oldest tick rather than block the clock
                with contextlib.suppress(asyncio.QueueEmpty):
                    queue.get_nowait()
            queue.put_nowait(tick)
        return tick

    def history(self, count: int) -> tuple[np.ndarray, np.ndarray]:
        count = min(count, len(self.prices))
        start = len(self.prices) - count
        epochs = np.fromiter(itertools.islice(self.epochs, start, None), dtype=np.int64, count=count)
        prices = np.fromiter(itertools.islice(self.prices, start, None), dtype=float, count=count)
        return epochs, prices


class SyntheticMarket:
    def __init__(self, seed: int = 42, history_size: int = 50_000, now: int | None = None):
        now = int(time.time()) if now is None else now
        seeds = np.random.SeedSequence(seed).spawn(len(CATALOG))
        self._feeds = {
            spec.symbol: Feed(spec, np.random.default_rng(s), history_size, now)
            for spec, s in zip(CATALOG, seeds, strict=True)
        }
        self._clock: asyncio.Task[None] | None = None

    # ---------------------------------------------------------------- lifecycle

    def start(self) -> None:
        if self._clock is None:
            self._clock = asyncio.create_task(self._run_clock())

    async def stop(self) -> None:
        if self._clock:
            self._clock.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._clock
            self._clock = None

    def tick_until(self, now: int) -> int:
        """Emit every tick due up to ``now``. Returns how many were emitted."""
        emitted = 0
        for feed in self._feeds.values():
            while feed.last_epoch + feed.spec.interval_s <= now:
                feed.advance(feed.last_epoch + feed.spec.interval_s)
                emitted += 1
        return emitted

    async def _run_clock(self) -> None:
        while True:
            self.tick_until(int(time.time()))
            await asyncio.sleep(1 - (time.time() % 1) + 0.01)  # wake just after each second

    # ---------------------------------------------------------------- queries

    def feed(self, symbol: str) -> Feed:
        try:
            return self._feeds[symbol.upper()]
        except KeyError:
            suggestions = difflib.get_close_matches(symbol.upper(), self._feeds, n=3, cutoff=0.4)
            raise UnknownSymbolError(symbol, suggestions) from None

    def symbols(self) -> list[dict[str, Any]]:
        return [
            {
                "symbol": f.spec.symbol,
                "name": f.spec.name,
                "category": f.spec.category,
                "tick_interval_s": f.spec.interval_s,
                "decimals": f.spec.decimals,
                "description": f.spec.description,
                "design_vol": f.spec.design_vol,
                "last_price": round(f.prices[-1], f.spec.decimals),
            }
            for f in self._feeds.values()
        ]

    def history(self, symbol: str, count: int) -> tuple[np.ndarray, np.ndarray]:
        return self.feed(symbol).history(count)

    def candles(self, symbol: str, granularity_s: int, count: int) -> list[dict[str, float]]:
        """OHLC candles aggregated from the tick history, oldest first."""
        feed = self.feed(symbol)
        epochs, prices = feed.history(len(feed.prices))
        buckets = epochs // granularity_s
        edges = np.flatnonzero(np.diff(buckets)) + 1
        starts = np.concatenate([[0], edges])
        ends = np.concatenate([edges, [len(prices)]])
        candles = [
            {
                "epoch": int(buckets[s] * granularity_s),
                "open": float(prices[s]),
                "high": float(prices[s:e].max()),
                "low": float(prices[s:e].min()),
                "close": float(prices[e - 1]),
            }
            for s, e in zip(starts, ends, strict=True)
        ]
        return candles[-count:]

    @contextlib.asynccontextmanager
    async def listen(self, symbol: str) -> AsyncIterator[asyncio.Queue[dict[str, Any]]]:
        feed = self.feed(symbol)
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=LISTENER_QUEUE_SIZE)
        feed.listeners.add(queue)
        try:
            yield queue
        finally:
            feed.listeners.discard(queue)
