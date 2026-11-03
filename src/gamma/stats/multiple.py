"""Adjustments for testing several metrics at once."""

from __future__ import annotations

import numpy as np


def holm(p_values: list[float]) -> list[float]:
    """Holm-Bonferroni adjusted p-values: controls the chance of ANY false positive, uniformly
    more powerful than Bonferroni and as simple to explain."""
    p = np.asarray(p_values, dtype=float)
    m = len(p)
    order = np.argsort(p)
    adjusted = np.empty(m)
    running = 0.0
    for rank, i in enumerate(order):
        running = max(running, (m - rank) * p[i])
        adjusted[i] = min(1.0, running)
    return adjusted.tolist()


def benjamini_hochberg(p_values: list[float]) -> list[float]:
    """Adjusted p-values controlling the false discovery rate: for exploring many metrics where a
    few false leads are acceptable."""
    p = np.asarray(p_values, dtype=float)
    m = len(p)
    order = np.argsort(p)[::-1]
    adjusted = np.empty(m)
    running = 1.0
    for rank, i in enumerate(order):
        running = min(running, p[i] * m / (m - rank))
        adjusted[i] = running
    return adjusted.tolist()
