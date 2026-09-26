from __future__ import annotations

import math

import numpy as np


def downsample(epochs: np.ndarray, values: np.ndarray, max_points: int = 300) -> list[dict[str, float]]:
    """Evenly thin a series for charting, always keeping the last point. Drops NaNs."""
    n = min(len(epochs), len(values))
    if n == 0:
        return []
    idx = np.arange(n) if n <= max_points else np.unique(np.linspace(0, n - 1, max_points).astype(int))
    out = []
    for i in idx:
        v = float(values[i])
        if not math.isnan(v):
            out.append({"t": int(epochs[i]), "v": v})
    return out
