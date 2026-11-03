"""Checks of the methods themselves, by simulation on realistic data.

A p-value is a claim about how often a procedure is wrong. Here the claim is tested: take the
players of an experiment that is known to have no effect, split them at random thousands of times
(an A/A test), run the production estimators, and count how often they cry wolf. Then plant a
known lift and count how often they find it, and whether the interval covers the truth.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy import stats

from ..analyze import estimate_metric
from ..config import Metric
from . import design, quality, sequential


@dataclass(frozen=True)
class Rate:
    successes: int
    trials: int

    @property
    def value(self) -> float:
        return self.successes / self.trials

    @property
    def se(self) -> float:
        p = self.value
        return float(np.sqrt(max(p * (1 - p), 1e-12) / self.trials))

    def __str__(self) -> str:
        return f"{self.value:.1%} ± {1.96 * self.se:.1%}"


Population = dict[str, np.ndarray]


def _split(pop: Population, n: int, rng: np.random.Generator) -> tuple[Population, Population]:
    size = len(next(iter(pop.values())))
    idx = rng.permutation(size)[: 2 * n]
    c, t = idx[:n], idx[n:]
    return {k: v[c] for k, v in pop.items()}, {k: v[t] for k, v in pop.items()}


def _plant(metric: Metric, t: Population, lift: float, rng: np.random.Generator) -> Population:
    """Treatment arm with a known relative lift of the metric, pre-period untouched."""
    out = dict(t)
    x = t[metric.num]
    if metric.kind == "binary":
        p = x.mean()
        flip = rng.random(len(x)) < lift * p / (1 - p)  # turn zeros into ones: p -> p (1 + lift)
        out[metric.num] = np.where((x == 0) & flip, 1.0, x)
    else:
        out[metric.num] = x * (1 + lift)
    return out


def false_positive_rates(
    pop: Population,
    metrics: list[Metric],
    n: int,
    trials: int,
    seed: int = 0,
    alpha: float = 0.05,
) -> dict[str, dict[str, Rate]]:
    """A/A: share of random splits declared significant, per metric and method."""
    rng = np.random.default_rng(seed)
    hits: dict[str, dict[str, int]] = {m.name: {} for m in metrics}
    for _ in range(trials):
        c, t = _split(pop, n, rng)
        for m in metrics:
            raw, adj = estimate_metric(m, c, t, alpha)
            for est in (raw, adj):
                if est is not None:
                    hits[m.name][est.method] = hits[m.name].get(est.method, 0) + (est.p < alpha)
    return {
        name: {method: Rate(h, trials) for method, h in methods.items()}
        for name, methods in hits.items()
    }


@dataclass(frozen=True)
class PowerRow:
    metric: str
    lift: float
    n: int
    planned_power: float
    raw: Rate
    cuped: Rate | None
    coverage: Rate  # of the 95% interval around the planted lift (the method that decides)
    variance_ratio: float | None  # var(CUPED estimate) / var(raw estimate)


def power_and_coverage(
    pop: Population,
    metric: Metric,
    lift: float,
    trials: int,
    seed: int = 0,
    alpha: float = 0.05,
    power: float = 0.8,
) -> PowerRow:
    """Plant `lift`, run at the sample size the design formula prescribes, count detections."""
    rng = np.random.default_rng(seed)
    x = pop[metric.num]
    if metric.kind == "binary":
        n = design.sample_size_binary(float(x.mean()), lift, alpha, power)
    elif metric.kind == "continuous":
        n = design.sample_size_mean(float(x.mean()), float(x.std(ddof=1)), lift, alpha, power)
    else:
        raise ValueError("power is checked for binary and continuous metrics")
    n = min(n, len(x) // 2)
    raw_hits = cuped_hits = covered = 0
    raw_diffs, cuped_diffs = [], []
    truth_rel = lift
    has_cuped = metric.pre is not None
    for _ in range(trials):
        c, t = _split(pop, n, rng)
        t = _plant(metric, t, lift, rng)
        raw, adj = estimate_metric(metric, c, t, alpha)
        raw_hits += raw.p < alpha
        raw_diffs.append(raw.diff)
        decider = adj or raw
        covered += decider.rel_ci[0] <= truth_rel <= decider.rel_ci[1]
        if adj is not None:
            cuped_hits += adj.p < alpha
            cuped_diffs.append(adj.diff)
    return PowerRow(
        metric=metric.name,
        lift=lift,
        n=n,
        planned_power=power,
        raw=Rate(raw_hits, trials),
        cuped=Rate(cuped_hits, trials) if has_cuped else None,
        coverage=Rate(covered, trials),
        variance_ratio=float(np.var(cuped_diffs) / np.var(raw_diffs)) if cuped_diffs else None,
    )


@dataclass(frozen=True)
class PeekingResult:
    looks: int
    naive: Rate
    sequential: Rate
    fixed: Rate


def peeking(
    pop: Population,
    metric: Metric,
    n: int,
    looks: int,
    trials: int,
    seed: int = 0,
    alpha: float = 0.05,
) -> PeekingResult:
    """A/A tests looked at `looks` times. Naive: stop at the first p < alpha. Sequential: the same
    looks against O'Brien-Fleming boundaries. Fixed: one look at the end."""
    assert metric.kind == "binary"
    rng = np.random.default_rng(seed)
    bounds = sequential.boundaries([(k + 1) / looks for k in range(looks)], alpha)
    z_naive = float(stats.norm.ppf(1 - alpha / 2))
    x = pop[metric.num]
    naive = seq = fixed = 0
    for _ in range(trials):
        idx = rng.permutation(len(x))[: 2 * n]
        arm = rng.permutation(np.r_[np.zeros(n), np.ones(n)])
        v = x[idx]
        # arrival order is the order of idx; each look sees a prefix of it
        cs_c = np.cumsum(np.where(arm == 0, v, 0.0))
        cs_t = np.cumsum(np.where(arm == 1, v, 0.0))
        cnt_c = np.cumsum(arm == 0)
        cnt_t = np.cumsum(arm == 1)
        zs = []
        for k in range(looks):
            # look k sees the first (k+1)/looks of all 2n arrivals
            pos = int(2 * n * (k + 1) / looks) - 1
            nc, nt = cnt_c[pos], cnt_t[pos]
            pc, pt = cs_c[pos] / nc, cs_t[pos] / nt
            pool = (cs_c[pos] + cs_t[pos]) / (nc + nt)
            se = np.sqrt(pool * (1 - pool) * (1 / nc + 1 / nt))
            zs.append(abs(pt - pc) / se if se > 0 else 0.0)
        zs_arr = np.array(zs)
        naive += bool((zs_arr > z_naive).any())
        seq += bool((zs_arr > np.array(bounds)).any())
        fixed += bool(zs_arr[-1] > z_naive)
    return PeekingResult(looks, Rate(naive, trials), Rate(seq, trials), Rate(fixed, trials))


def srm_rates(n: int, trials: int, drop: float, seed: int = 0) -> tuple[Rate, Rate]:
    """False alarm rate of the SRM check on honest 50/50 splits, and its detection rate when a
    share `drop` of one arm's players goes missing."""
    rng = np.random.default_rng(seed)
    false_alarm = detected = 0
    for _ in range(trials):
        a = int(rng.binomial(2 * n, 0.5))
        b = 2 * n - a
        false_alarm += quality.srm_test(
            {"control": a, "treatment": b}, {"control": 1, "treatment": 1}
        ).failed
        b_lost = int(b * (1 - drop))
        detected += quality.srm_test(
            {"control": a, "treatment": b_lost}, {"control": 1, "treatment": 1}
        ).failed
    return Rate(false_alarm, trials), Rate(detected, trials)
