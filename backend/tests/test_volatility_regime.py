import numpy as np
import pytest

from app.quant.regime import detect_regimes, noise_band
from app.quant.volatility import (
    detect_jumps,
    log_returns,
    periods_per_year,
    volatility_report,
)

from .conftest import random_walk


def test_annualisation_uses_sampling_interval():
    epochs = np.arange(0, 100, 2)
    assert periods_per_year(epochs) == 365 * 24 * 3600 / 2


def test_recovers_nominal_volatility(walk):
    """A Volatility 75 index is designed to have 75% annualised vol; the estimator should find it."""
    epochs, prices = walk
    report = volatility_report(epochs, prices)
    assert report["realized_vol"] == pytest.approx(0.75, abs=0.03)
    assert 0.4 < report["ewma_vol"] < 1.2
    assert report["garch"] is not None
    assert report["garch"]["forecast_vol"] == pytest.approx(0.75, abs=0.1)
    assert 0 <= report["current_percentile"] <= 100


def test_detects_injected_jump():
    _, prices = random_walk(n=3000, seed=2)
    returns = log_returns(prices)
    returns[1234] += 0.01  # ~50 sigma
    assert 1234 in detect_jumps(returns)


def test_constant_volatility_is_one_regime(walk):
    epochs, prices = walk
    result = detect_regimes(epochs, prices)
    assert result["time_share"]["normal"] >= 0.9
    assert "stable" in result["summary"]


def test_finds_turbulent_block():
    e1, p1 = random_walk(n=2000, sigma_annual=0.25, seed=10)
    _, p2 = random_walk(n=1000, sigma_annual=1.0, seed=11, start=p1[-1])
    _, p3 = random_walk(n=2000, sigma_annual=0.25, seed=12, start=p2[-1])
    prices = np.concatenate([p1, p2[1:], p3[1:]])
    epochs = 1_700_000_000 + np.arange(len(prices)) * 2
    result = detect_regimes(epochs, prices)
    assert 0.1 < result["time_share"]["turbulent"] < 0.4
    assert result["current_regime"] != "turbulent"
    assert any(s["label"] == "turbulent" for s in result["segments"])


def test_noise_band_shrinks_with_window():
    assert noise_band(400) < noise_band(100) < noise_band(25)
