"""Checks that decide whether a test result may be read at all."""

from __future__ import annotations

from dataclasses import dataclass

from scipy import stats

# The convention (Kohavi et al.): a very small threshold, because a real SRM almost always has a
# p-value near zero and a false alarm on every tenth test would train people to ignore the check.
SRM_THRESHOLD = 0.001


@dataclass(frozen=True)
class Srm:
    observed: dict[str, int]
    expected_share: dict[str, float]
    chi2: float
    p: float

    @property
    def failed(self) -> bool:
        return self.p < SRM_THRESHOLD

    def describe(self) -> str:
        total = sum(self.observed.values())
        parts = [
            f"{v}: {n} ({n / total:.2%} vs {self.expected_share[v]:.2%} planned)"
            for v, n in self.observed.items()
        ]
        return ", ".join(parts) + f"; chi2={self.chi2:.1f}, p={self.p:.3g}"


def srm_test(observed: dict[str, int], weights: dict[str, float]) -> Srm:
    """Sample ratio mismatch: do the arm sizes match the planned split?

    A mismatch means players were lost or added unevenly, and then the arms are no longer
    comparable, whatever p-value the metric gives.
    """
    total_w = sum(weights.values())
    share = {v: w / total_w for v, w in weights.items()}
    n = sum(observed.get(v, 0) for v in weights)
    obs = [observed.get(v, 0) for v in weights]
    exp = [share[v] * n for v in weights]
    chi2, p = stats.chisquare(obs, exp)
    return Srm({v: observed.get(v, 0) for v in weights}, share, float(chi2), float(p))
