"""How many players a test needs, before it starts."""

from __future__ import annotations

import math

from scipy import stats


def sample_size_binary(baseline: float, mde: float, alpha: float = 0.05, power: float = 0.8) -> int:
    """Players per arm to detect a relative change `mde` of a rate (two-sided two-proportion z)."""
    p1, p2 = baseline, baseline * (1 + mde)
    if not 0 < p1 < 1 or not 0 < p2 < 1:
        raise ValueError(f"rate {p1:.3f} with a relative change of {mde:+.1%} leaves (0, 1)")
    z_a, z_b = stats.norm.ppf(1 - alpha / 2), stats.norm.ppf(power)
    p_bar = (p1 + p2) / 2
    num = z_a * math.sqrt(2 * p_bar * (1 - p_bar)) + z_b * math.sqrt(p1 * (1 - p1) + p2 * (1 - p2))
    return math.ceil(num**2 / (p2 - p1) ** 2)


def sample_size_mean(
    mean: float,
    sd: float,
    mde: float,
    alpha: float = 0.05,
    power: float = 0.8,
    variance_reduction: float = 0.0,
) -> int:
    """Players per arm to detect a relative change `mde` of a mean (two-sided, equal variances).

    `variance_reduction` is the share of variance CUPED removes (rho squared): the same power
    needs that much fewer players.
    """
    if mean == 0:
        raise ValueError("the baseline mean is 0, a relative change is undefined")
    z_a, z_b = stats.norm.ppf(1 - alpha / 2), stats.norm.ppf(power)
    var = sd**2 * (1 - variance_reduction)
    return math.ceil(2 * (z_a + z_b) ** 2 * var / (mean * mde) ** 2)


def power_binary(baseline: float, mde: float, n_per_arm: int, alpha: float = 0.05) -> float:
    """Chance to detect a relative change `mde` of a rate with n players per arm."""
    p1, p2 = baseline, baseline * (1 + mde)
    z_a = stats.norm.ppf(1 - alpha / 2)
    se = math.sqrt(p1 * (1 - p1) / n_per_arm + p2 * (1 - p2) / n_per_arm)
    return float(stats.norm.cdf(abs(p2 - p1) / se - z_a))


def power_mean(
    mean: float, sd: float, mde: float, n_per_arm: int, alpha: float = 0.05, reduction: float = 0.0
) -> float:
    z_a = stats.norm.ppf(1 - alpha / 2)
    se = math.sqrt(2 * sd**2 * (1 - reduction) / n_per_arm)
    return float(stats.norm.cdf(abs(mean * mde) / se - z_a))
