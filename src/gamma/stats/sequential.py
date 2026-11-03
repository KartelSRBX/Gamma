"""Group-sequential boundaries: how to look at a running test without inflating errors.

Testing at 5% every day and stopping at the first "significant" result makes a no-effect test
"win" far more than 5% of the time. The honest ways out are a fixed horizon (look once) or a
plan: decide the number of looks in advance and spend the 5% across them. Here the spending
function is O'Brien-Fleming's: almost nothing is spent early, so an early stop needs overwhelming
evidence and the final look is close to the fixed-horizon test.
"""

from __future__ import annotations

from itertools import pairwise

import numpy as np
from scipy import optimize, stats


def obrien_fleming_spending(t: float, alpha: float = 0.05) -> float:
    """Cumulative two-sided alpha spent at information fraction t in (0, 1]."""
    return float(2 * (1 - stats.norm.cdf(stats.norm.ppf(1 - alpha / 2) / np.sqrt(t))))


def boundaries(looks: list[float], alpha: float = 0.05, grid: int = 4001) -> list[float]:
    """Two-sided critical z-values for looks at the given information fractions (increasing,
    the last one 1.0), such that the chance of EVER crossing under no effect is `alpha`.

    Done by numerical integration over the score process S_k ~ N(0, t_k): at each look the density
    of the still-running paths is propagated through the Gaussian increment, and the boundary is
    the one that spends exactly the planned alpha at that look.
    """
    if any(b <= a for a, b in pairwise(looks)) or looks[-1] != 1.0:
        raise ValueError("looks must increase and end at 1.0")
    limit = 8.0
    x = np.linspace(-limit, limit, grid)
    dx = x[1] - x[0]
    spent_before = 0.0
    out: list[float] = []
    density = None  # sub-density of S on the grid, running paths only
    t_prev = 0.0
    for t in looks:
        sd = np.sqrt(t - t_prev)
        if density is None:
            f = stats.norm.pdf(x, scale=sd)
        else:
            # propagate: f_k(y) = sum_x g(x) phi((y - x) / sd) / sd * dx
            kernel = stats.norm.pdf(x[:, None] - x[None, :], scale=sd)
            f = kernel @ density * dx
        target_stop = obrien_fleming_spending(t, alpha) - spent_before
        cdf = np.concatenate([[0.0], np.cumsum((f[1:] + f[:-1]) / 2 * dx)])
        total = cdf[-1]

        def mass_inside(b: float, cdf=cdf) -> float:
            lo = np.interp(-b, x, cdf)
            hi = np.interp(b, x, cdf)
            return hi - lo

        want_inside = total - target_stop
        if target_stop <= 1e-12:
            b = limit - 1e-6
        else:
            b = optimize.brentq(lambda b, w=want_inside: mass_inside(b) - w, 1e-6, limit - 1e-6)
        out.append(b / np.sqrt(t))
        density = np.where(np.abs(x) < b, f, 0.0)
        spent_before += target_stop
        t_prev = t
    return [float(b) for b in out]
