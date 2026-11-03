"""Estimators of the difference between two arms.

Every function takes per-player values (the randomisation unit) and returns an `Estimate`.
All variants reduce to "a mean per arm and the variance of that mean", so the final step is
shared. The way each one gets its variance is the point:

* binary      two-proportion z-test (pooled variance for the p-value, unpooled for the interval)
* continuous  Welch's t-test: unequal variances, which money metrics always have
* ratio       delta method: the ratio of two sums over players is not a mean of independent
              terms, treating it as one understates the variance
* cuped       Welch on values adjusted by the pre-period, same expectation, smaller variance
"""

from __future__ import annotations

from dataclasses import dataclass, replace

import numpy as np
from scipy import stats


@dataclass(frozen=True)
class Estimate:
    method: str
    n_control: int
    n_treatment: int
    mean_control: float
    mean_treatment: float
    diff: float
    se: float
    ci: tuple[float, float]
    rel_diff: float
    rel_ci: tuple[float, float]
    p: float
    # CUPED only: adjustment coefficient and the variance it removed
    theta: float | None = None
    variance_reduction: float | None = None

    @property
    def significant(self) -> bool:
        return self.p < 0.05


def _combine(
    method: str,
    n_c: int,
    n_t: int,
    m_c: float,
    m_t: float,
    var_mean_c: float,
    var_mean_t: float,
    alpha: float,
    p: float | None = None,
    dof: float | None = None,
) -> Estimate:
    """Difference of two independent estimates with known variances of the estimators."""
    diff = m_t - m_c
    se = float(np.sqrt(var_mean_c + var_mean_t))
    if dof is None:
        # Welch-Satterthwaite with n - 1 degrees of freedom per arm
        denom = var_mean_c**2 / max(n_c - 1, 1) + var_mean_t**2 / max(n_t - 1, 1)
        dof = (var_mean_c + var_mean_t) ** 2 / denom if denom > 0 else np.inf
    crit = stats.t.ppf(1 - alpha / 2, dof)
    if p is None:
        p = 2 * stats.t.sf(abs(diff) / se, dof) if se > 0 else 1.0
    rel = diff / m_c if m_c else float("nan")
    # delta method for t/c - 1
    rel_se = np.sqrt(var_mean_t / m_c**2 + m_t**2 * var_mean_c / m_c**4) if m_c else float("nan")
    return Estimate(
        method=method,
        n_control=n_c,
        n_treatment=n_t,
        mean_control=float(m_c),
        mean_treatment=float(m_t),
        diff=float(diff),
        se=se,
        ci=(float(diff - crit * se), float(diff + crit * se)),
        rel_diff=float(rel),
        rel_ci=(float(rel - crit * rel_se), float(rel + crit * rel_se)),
        p=float(p),
    )


def binary_test(c: np.ndarray, t: np.ndarray, alpha: float = 0.05) -> Estimate:
    n_c, n_t = len(c), len(t)
    p_c, p_t = c.mean(), t.mean()
    pooled = (c.sum() + t.sum()) / (n_c + n_t)
    se0 = np.sqrt(pooled * (1 - pooled) * (1 / n_c + 1 / n_t))
    p = 2 * stats.norm.sf(abs(p_t - p_c) / se0) if se0 > 0 else 1.0
    return _combine(
        "two-proportion z",
        n_c,
        n_t,
        p_c,
        p_t,
        p_c * (1 - p_c) / n_c,
        p_t * (1 - p_t) / n_t,
        alpha,
        p=p,
        dof=np.inf,
    )


def welch_test(c: np.ndarray, t: np.ndarray, alpha: float = 0.05) -> Estimate:
    n_c, n_t = len(c), len(t)
    return _combine(
        "Welch t",
        n_c,
        n_t,
        c.mean(),
        t.mean(),
        c.var(ddof=1) / n_c,
        t.var(ddof=1) / n_t,
        alpha,
    )


def _ratio_arm(num: np.ndarray, den: np.ndarray) -> tuple[float, float]:
    """Ratio of sums and the variance of that estimator (delta method)."""
    n = len(num)
    r = num.sum() / den.sum()
    mean_den = den.mean()
    # linearisation: the ratio behaves like the mean of (x - r y) / mean(y)
    u = (num - r * den) / mean_den
    return float(r), float(u.var(ddof=1) / n)


def ratio_test(
    num_c: np.ndarray,
    den_c: np.ndarray,
    num_t: np.ndarray,
    den_t: np.ndarray,
    alpha: float = 0.05,
) -> Estimate:
    r_c, v_c = _ratio_arm(num_c, den_c)
    r_t, v_t = _ratio_arm(num_t, den_t)
    return _combine("delta method", len(num_c), len(num_t), r_c, r_t, v_c, v_t, alpha, dof=np.inf)


def cuped_adjust(
    y_c: np.ndarray, x_c: np.ndarray, y_t: np.ndarray, x_t: np.ndarray
) -> tuple[np.ndarray, np.ndarray, float, float]:
    """CUPED: y' = y - theta (x - mean(x)), with x the same metric before exposure.

    theta is estimated on both arms pooled, so it cannot be tuned towards a result, and x is
    measured before the player saw any variant, so the adjustment cannot remove a real effect:
    E[y'] = E[y] in each arm. Returns adjusted values, theta and the share of variance removed.
    """
    y = np.concatenate([y_c, y_t])
    x = np.concatenate([x_c, x_t])
    var_x = x.var(ddof=1)
    if var_x == 0:
        return y_c, y_t, 0.0, 0.0
    theta = float(np.cov(x, y, ddof=1)[0, 1] / var_x)
    mean_x = x.mean()
    adj_c = y_c - theta * (x_c - mean_x)
    adj_t = y_t - theta * (x_t - mean_x)
    reduction = 1 - np.concatenate([adj_c, adj_t]).var(ddof=1) / y.var(ddof=1)
    return adj_c, adj_t, theta, float(reduction)


def cuped_test(
    kind: str,
    y_c: np.ndarray,
    x_c: np.ndarray,
    y_t: np.ndarray,
    x_t: np.ndarray,
    alpha: float = 0.05,
) -> Estimate:
    """Welch's test on CUPED-adjusted values. The means are covariate-adjusted: each arm's mean
    minus theta times how far that arm's pre-period mean sits from the pooled one. When
    randomisation balanced the pre-period perfectly they equal the raw means."""
    adj_c, adj_t, theta, reduction = cuped_adjust(y_c, x_c, y_t, x_t)
    est = _combine(
        "CUPED" + (" (linear on 0/1)" if kind == "binary" else ""),
        len(y_c),
        len(y_t),
        adj_c.mean(),
        adj_t.mean(),
        adj_c.var(ddof=1) / len(adj_c),
        adj_t.var(ddof=1) / len(adj_t),
        alpha,
    )
    return replace(est, theta=theta, variance_reduction=reduction)


def bootstrap_diff_ci(
    c: np.ndarray,
    t: np.ndarray,
    alpha: float = 0.05,
    resamples: int = 2000,
    seed: int = 0,
) -> tuple[float, float]:
    """Percentile bootstrap interval of the difference in means, resampling players.

    A cross-check for heavy-tailed metrics: if it disagrees with the Welch interval, the sample is
    too small or too skewed for the normal approximation.
    """
    rng = np.random.default_rng(seed)
    diffs = np.empty(resamples)
    for i in range(resamples):
        diffs[i] = (
            t[rng.integers(0, len(t), len(t))].mean() - c[rng.integers(0, len(c), len(c))].mean()
        )
    lo, hi = np.quantile(diffs, [alpha / 2, 1 - alpha / 2])
    return float(lo), float(hi)
