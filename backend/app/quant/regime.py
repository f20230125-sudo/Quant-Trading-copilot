"""Volatility regime detection with a noise-aware threshold.

A naive "split rolling vol into terciles" labeller always finds calm and
turbulent periods, even in a constant-volatility random walk. Here a bar is
only labelled calm/turbulent when its rolling volatility deviates from the
median by more than the sampling error of a rolling standard deviation could
explain (about 1/sqrt(2(n-1)) in relative terms for a window of n).
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np

from .volatility import log_returns, periods_per_year, rolling_vol

LABELS = ("calm", "normal", "turbulent")
Z_THRESHOLD = 3.0


def noise_band(window: int, z: float = Z_THRESHOLD) -> float:
    """Relative deviation of rolling vol that sampling noise alone rarely exceeds."""
    return z / math.sqrt(2 * (window - 1))


def _segments(labels: np.ndarray) -> list[tuple[int, int, int]]:
    """Run-length encode labels into (start, end_inclusive, label) triples."""
    segs: list[tuple[int, int, int]] = []
    start = 0
    for i in range(1, len(labels) + 1):
        if i == len(labels) or labels[i] != labels[start]:
            segs.append((start, i - 1, int(labels[start])))
            start = i
    return segs


def _merge_short(labels: np.ndarray, min_duration: int) -> np.ndarray:
    """Absorb segments shorter than ``min_duration`` into the preceding segment."""
    labels = labels.copy()
    segs = _segments(labels)
    for idx, (start, end, _) in enumerate(segs):
        if idx > 0 and end - start + 1 < min_duration:
            labels[start : end + 1] = labels[start - 1]
    return labels


def detect_regimes(epochs: np.ndarray, prices: np.ndarray, window: int = 100) -> dict[str, Any]:
    epochs = np.asarray(epochs)
    returns = log_returns(prices)
    window = max(10, min(window, len(returns) // 4))
    per_year = periods_per_year(epochs)
    roll = rolling_vol(returns, window, per_year)

    valid_mask = ~np.isnan(roll)
    vol = roll[valid_mask]
    vol_epochs = epochs[1:][valid_mask]
    median = float(np.median(vol))
    band = noise_band(window)

    labels = np.ones(len(vol), dtype=int)  # normal
    labels[vol < median * (1 - band)] = 0
    labels[vol > median * (1 + band)] = 2
    labels = _merge_short(labels, min_duration=max(5, window // 2))

    segments = [
        {
            "label": LABELS[lab],
            "start_epoch": int(vol_epochs[s]),
            "end_epoch": int(vol_epochs[e]),
            "bars": e - s + 1,
            "mean_vol": float(vol[s : e + 1].mean()),
        }
        for s, e, lab in _segments(labels)
    ]
    share = {LABELS[k]: float((labels == k).mean()) for k in range(3)}

    if share["normal"] >= 0.95:
        summary = (
            "Volatility is stable: rolling volatility stayed within the band explained by "
            "sampling noise for at least 95% of the window. Apparent 'regimes' would be noise."
        )
    else:
        summary = (
            f"Volatility varied beyond sampling noise: {share['turbulent']:.0%} of the window "
            f"was turbulent and {share['calm']:.0%} calm."
        )

    return {
        "window": window,
        "median_vol": median,
        "noise_band_pct": band * 100,
        "current_regime": LABELS[int(labels[-1])],
        "current_vol": float(vol[-1]),
        "time_share": share,
        "n_switches": len(segments) - 1,
        "segments": segments[-20:],
        "summary": summary,
        "_rolling": (vol_epochs, vol),
    }
