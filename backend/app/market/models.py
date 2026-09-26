"""Stochastic price models for the synthetic indices.

Each model generates the next ``n`` prices from the last price and carries any
state it needs (current volatility regime, last return) between calls, so a
backfill of 50,000 ticks and a live stream of single ticks produce the same process.
"""

from __future__ import annotations

import math
from abc import ABC, abstractmethod

import numpy as np

SECONDS_PER_YEAR = 365 * 24 * 3600


def per_tick_sigma(annual_sigma: float, interval_s: float) -> float:
    return annual_sigma * math.sqrt(interval_s / SECONDS_PER_YEAR)


class PriceModel(ABC):
    @abstractmethod
    def generate(self, last_price: float, n: int, rng: np.random.Generator) -> np.ndarray:
        """Return ``n`` new prices following ``last_price``."""


class GBM(PriceModel):
    """Geometric Brownian motion with constant volatility and zero expected return."""

    def __init__(self, annual_sigma: float, interval_s: float):
        self.sigma = per_tick_sigma(annual_sigma, interval_s)

    def log_returns(self, n: int, rng: np.random.Generator) -> np.ndarray:
        return rng.normal(-0.5 * self.sigma**2, self.sigma, n)

    def generate(self, last_price, n, rng):
        return last_price * np.exp(np.cumsum(self.log_returns(n, rng)))


class JumpDiffusion(GBM):
    """GBM plus Poisson jumps whose size is a multiple of the per-tick volatility."""

    def __init__(self, annual_sigma: float, interval_s: float, jumps_per_hour: float = 3, jump_multiple: float = 30):
        super().__init__(annual_sigma, interval_s)
        self.jump_prob = jumps_per_hour * interval_s / 3600
        self.jump_sigma = jump_multiple * self.sigma

    def log_returns(self, n, rng):
        base = super().log_returns(n, rng)
        jumps = rng.random(n) < self.jump_prob
        base[jumps] += rng.normal(0, self.jump_sigma, int(jumps.sum()))
        return base


class CrashBoom(PriceModel):
    """Steady drift punctuated by rare, sharp moves the other way.

    direction=-1 gives a crash index (drifts up, crashes down); +1 gives a boom
    index. Event sizes are exponential with a mean that offsets the drift, so the
    expected return is roughly zero: the drift is compensation, not an edge.
    """

    def __init__(self, direction: int, avg_ticks_between: int, drift_per_tick: float = 5e-5, noise: float = 2e-5):
        self.direction = direction
        self.event_prob = 1 / avg_ticks_between
        self.drift = drift_per_tick
        self.noise = noise
        self.mean_event = drift_per_tick * avg_ticks_between

    def generate(self, last_price, n, rng):
        lr = rng.normal(-self.direction * self.drift, self.noise, n)
        events = rng.random(n) < self.event_prob
        lr[events] = self.direction * rng.exponential(self.mean_event, int(events.sum()))
        return last_price * np.exp(np.cumsum(lr))


class StepModel(PriceModel):
    """Moves exactly one fixed step up or down on every tick."""

    def __init__(self, step: float = 0.1):
        self.step = step

    def generate(self, last_price, n, rng):
        steps = rng.choice([-self.step, self.step], n)
        return np.round(last_price + np.cumsum(steps), 6)


class RegimeSwitching(PriceModel):
    """Two-state Markov-switching volatility: calm and turbulent regimes."""

    def __init__(self, annual_sigmas: tuple[float, float], mean_regime_s: float, interval_s: float):
        self.sigmas = np.array([per_tick_sigma(s, interval_s) for s in annual_sigmas])
        self.switch_prob = interval_s / mean_regime_s
        self.state = 0

    def generate(self, last_price, n, rng):
        flips = rng.random(n) < self.switch_prob
        states = (self.state + np.cumsum(flips)) % 2
        self.state = int(states[-1])
        sig = self.sigmas[states]
        lr = rng.normal(0, 1, n) * sig - 0.5 * sig**2
        return last_price * np.exp(np.cumsum(lr))


class AR1Momentum(PriceModel):
    """Returns with positive first-order autocorrelation: a small, real, planted edge.

    Unconditional volatility still matches ``annual_sigma``. This index is the
    control case showing the backtester can detect an edge when one exists.
    """

    def __init__(self, annual_sigma: float, interval_s: float, phi: float = 0.15):
        sigma = per_tick_sigma(annual_sigma, interval_s)
        self.phi = phi
        self.eps_sigma = sigma * math.sqrt(1 - phi**2)
        self.last_return = 0.0

    def generate(self, last_price, n, rng):
        eps = rng.normal(0, self.eps_sigma, n)
        lr = np.empty(n)
        r = self.last_return
        for i in range(n):
            r = self.phi * r + eps[i]
            lr[i] = r
        self.last_return = r
        return last_price * np.exp(np.cumsum(lr))
