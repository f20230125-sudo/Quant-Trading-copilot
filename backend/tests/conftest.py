import numpy as np
import pytest


def random_walk(n: int = 5000, sigma_annual: float = 0.75, dt: float = 2.0, seed: int = 0, start: float = 1000.0):
    """Driftless GBM sampled every ``dt`` seconds, like a Deriv volatility index."""
    rng = np.random.default_rng(seed)
    per_year = 365 * 24 * 3600 / dt
    step_sigma = sigma_annual / np.sqrt(per_year)
    log_steps = rng.normal(-0.5 * step_sigma**2, step_sigma, size=n - 1)
    prices = start * np.exp(np.concatenate([[0.0], np.cumsum(log_steps)]))
    epochs = 1_700_000_000 + (np.arange(n) * dt).astype(int)
    return epochs, prices


@pytest.fixture
def walk():
    return random_walk()
