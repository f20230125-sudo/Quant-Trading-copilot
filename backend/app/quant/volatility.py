"""Volatility estimators for tick or candle series.

Deriv synthetic indices trade 24/7, so annualisation uses calendar seconds and
the series' own median sampling interval (2s for R_* indices, 1s for 1HZ*).
"""

from __future__ import annotations

import math
import warnings
from typing import Any

import numpy as np
import pandas as pd

SECONDS_PER_YEAR = 365 * 24 * 3600


def median_interval(epochs: np.ndarray) -> float:
    diffs = np.diff(np.asarray(epochs, dtype=float))
    diffs = diffs[diffs > 0]
    return float(np.median(diffs)) if len(diffs) else 1.0


def periods_per_year(epochs: np.ndarray) -> float:
    return SECONDS_PER_YEAR / median_interval(epochs)


def log_returns(prices: np.ndarray) -> np.ndarray:
    prices = np.asarray(prices, dtype=float)
    return np.diff(np.log(prices))


def realized_vol(returns: np.ndarray, per_year: float) -> float:
    if len(returns) < 2:
        return float("nan")
    return float(np.std(returns, ddof=1) * math.sqrt(per_year))


def rolling_vol(returns: np.ndarray, window: int, per_year: float) -> np.ndarray:
    series = pd.Series(returns).rolling(window).std(ddof=1)
    return series.to_numpy() * math.sqrt(per_year)


def ewma_vol(returns: np.ndarray, per_year: float, lam: float = 0.94) -> float:
    """RiskMetrics-style EWMA volatility at the last observation."""
    if len(returns) < 2:
        return float("nan")
    var = float(np.var(returns[: min(50, len(returns))]))
    for r in returns:
        var = lam * var + (1 - lam) * r * r
    return math.sqrt(var * per_year)


def garch_forecast(returns: np.ndarray, per_year: float, horizon: int) -> dict[str, float] | None:
    """Fit a zero-mean GARCH(1,1) and forecast average volatility over ``horizon`` periods.

    Returns are rescaled to unit variance before fitting (the optimiser is unstable on
    raw tick returns of ~1e-4), and the forecast is scaled back afterwards.
    Returns None if the fit fails; the caller reports the other estimators regardless.
    """
    from arch import arch_model

    if len(returns) < 200:
        return None
    scale = 1.0 / float(np.std(returns))
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            model = arch_model(returns * scale, mean="Zero", vol="GARCH", p=1, q=1, rescale=False)
            fit = model.fit(disp="off", show_warning=False)
            variance = fit.forecast(horizon=horizon, reindex=False).variance.to_numpy()[-1]
    except Exception:
        return None
    omega = float(fit.params["omega"])
    alpha = float(fit.params["alpha[1]"])
    beta = float(fit.params["beta[1]"])
    persistence = alpha + beta
    long_run = math.sqrt(omega / (1 - persistence)) / scale if persistence < 1 else float("nan")
    return {
        "forecast_vol": math.sqrt(float(np.mean(variance))) / scale * math.sqrt(per_year),
        "long_run_vol": long_run * math.sqrt(per_year),
        "alpha": alpha,
        "beta": beta,
        "persistence": persistence,
        "horizon_periods": horizon,
    }


def detect_jumps(returns: np.ndarray, threshold_sigma: float = 6.0) -> np.ndarray:
    """Indices of returns larger than ``threshold_sigma`` robust standard deviations.

    The scale is the median absolute return (about zero-mean at tick level), so the
    jumps themselves don't inflate it. Centring on the median instead would collapse
    the scale to ~0 on the Step index, where every move has the same size.
    """
    if len(returns) == 0:
        return np.array([], dtype=int)
    sigma = 1.4826 * float(np.median(np.abs(returns)))
    if sigma == 0:
        return np.array([], dtype=int)
    return np.flatnonzero(np.abs(returns) > threshold_sigma * sigma)


def volatility_report(
    epochs: np.ndarray, prices: np.ndarray, window: int = 100, horizon: int = 100
) -> dict[str, Any]:
    epochs = np.asarray(epochs)
    returns = log_returns(prices)
    per_year = periods_per_year(epochs)
    window = max(10, min(window, len(returns) // 4))

    roll = rolling_vol(returns, window, per_year)
    valid = roll[~np.isnan(roll)]
    current = float(valid[-1]) if len(valid) else float("nan")
    percentile = float((valid < current).mean() * 100) if len(valid) else float("nan")

    jumps = detect_jumps(returns)
    largest = int(np.argmax(np.abs(returns))) if len(returns) else None

    return {
        "n_returns": int(len(returns)),
        "sampling_interval_s": median_interval(epochs),
        "window": window,
        "realized_vol": realized_vol(returns, per_year),
        "current_rolling_vol": current,
        "current_percentile": percentile,
        "rolling_vol_min": float(valid.min()) if len(valid) else float("nan"),
        "rolling_vol_max": float(valid.max()) if len(valid) else float("nan"),
        "ewma_vol": ewma_vol(returns, per_year),
        "garch": garch_forecast(returns, per_year, horizon),
        "jumps": {
            "count": int(len(jumps)),
            "threshold_sigma": 6.0,
            "recent_epochs": [int(epochs[i + 1]) for i in jumps[-5:]],
        },
        "largest_move": None
        if largest is None
        else {"epoch": int(epochs[largest + 1]), "log_return": float(returns[largest])},
        # epochs aligned to the rolling series (return i spans epochs[i] -> epochs[i+1])
        "_rolling": (epochs[1:], roll),
    }
