"""Analysis of one experiment: checks first, estimates second.

The order is the point. An estimate on data that failed a quality check is a number, not a
finding, so the checks are computed first and carried next to every result.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

import numpy as np
from clickhouse_connect.driver.client import Client
from scipy import stats

from . import marts
from .config import Experiment, Metric
from .stats import design, estimators, multiple, quality

ALPHA_GUARDRAIL_SIDE = 2  # a one-sided guardrail at alpha is a two-sided interval at 2 * alpha


@dataclass
class MetricResult:
    metric: Metric
    role: str  # primary | secondary | guardrail
    raw: estimators.Estimate
    adjusted: estimators.Estimate | None = None
    p_adjusted: float | None = None  # Holm over the secondary metrics
    bootstrap_ci: tuple[float, float] | None = None
    guardrail: str | None = None  # ok | violated | inconclusive

    @property
    def estimate(self) -> estimators.Estimate:
        """What the decision uses: the variance-reduced estimate whenever the metric has one."""
        return self.adjusted or self.raw


@dataclass
class Plan:
    n_per_arm: int
    baseline: float
    sd: float
    achieved_power: float


@dataclass
class Analysis:
    experiment: Experiment
    as_of: datetime
    arms: dict[str, int]
    srm: quality.Srm
    excluded_multi_variant: int
    balance: dict[str, float]  # pre-period metric -> Holm-adjusted p of the difference between arms
    results: list[MetricResult]
    plan: Plan | None
    warnings: list[str] = field(default_factory=list)

    @property
    def at_horizon(self) -> bool:
        return self.as_of >= self.experiment.ends_at

    @property
    def valid(self) -> bool:
        return not self.srm.failed and not any(p < 0.001 for p in self.balance.values())


def _columns(metrics: list[Metric]) -> list[str]:
    cols: list[str] = []
    for m in metrics:
        for c in (m.num, m.den, m.pre):
            if c and c not in cols:
                cols.append(c)
    return cols


def load_arms(
    client: Client, key: str, columns: list[str]
) -> tuple[dict[str, dict[str, np.ndarray]], int]:
    """Per-player columns by variant, without players who saw several variants (counted apart)."""
    res = client.query(
        f"SELECT variant, {', '.join(columns)} FROM mart_user_metrics "
        "WHERE experiment = {e:String} AND n_variants = 1 ORDER BY player_id",
        parameters={"e": key},
    )
    variants = np.array(res.column_names and res.result_columns[0])
    arms: dict[str, dict[str, np.ndarray]] = {}
    for v in np.unique(variants):
        mask = variants == v
        arms[str(v)] = {
            col: np.asarray(res.result_columns[i + 1], dtype=float)[mask]
            for i, col in enumerate(columns)
        }
    multi = client.query(
        "SELECT count() FROM mart_user_metrics WHERE experiment = {e:String} AND n_variants > 1",
        parameters={"e": key},
    ).result_rows[0][0]
    return arms, int(multi)


def estimate_metric(
    metric: Metric, c: dict[str, np.ndarray], t: dict[str, np.ndarray], alpha: float
) -> tuple[estimators.Estimate, estimators.Estimate | None]:
    """Raw estimate, and the CUPED one when the metric has a pre-period column."""
    if metric.kind == "binary":
        raw = estimators.binary_test(c[metric.num], t[metric.num], alpha)
    elif metric.kind == "continuous":
        raw = estimators.welch_test(c[metric.num], t[metric.num], alpha)
    else:
        assert metric.den is not None
        raw = estimators.ratio_test(
            c[metric.num], c[metric.den], t[metric.num], t[metric.den], alpha
        )
    adjusted = None
    if metric.pre and metric.kind != "ratio":
        adjusted = estimators.cuped_test(
            metric.kind, c[metric.num], c[metric.pre], t[metric.num], t[metric.pre], alpha
        )
    return raw, adjusted


def guardrail_status(
    metric: Metric,
    c: dict[str, np.ndarray],
    t: dict[str, np.ndarray],
    max_drop: float,
    alpha: float,
) -> str:
    """Non-inferiority: is the metric worse than control by more than the allowed share?

    One-sided, so the interval is two-sided at 2 * alpha. `ok` needs the whole interval on the
    safe side of the margin; `violated` needs the whole interval beyond it; anything else is
    `inconclusive`, which is not a pass.
    """
    raw, adjusted = estimate_metric(metric, c, t, ALPHA_GUARDRAIL_SIDE * alpha)
    lo, hi = (adjusted or raw).rel_ci
    if metric.better == "higher":
        return "ok" if lo > -max_drop else "violated" if hi < -max_drop else "inconclusive"
    return "ok" if hi < max_drop else "violated" if lo > max_drop else "inconclusive"


def plan_from_data(
    metric: Metric, pre_values: np.ndarray, n_per_arm: int, mde: float, alpha: float, power: float
) -> Plan | None:
    """Sample size from the pre-period, which exists before the test and cannot be influenced by
    it. Ratio metrics have no pre-period column here, so they get no plan."""
    if metric.kind == "ratio":
        return None
    mean, sd = float(pre_values.mean()), float(pre_values.std(ddof=1))
    if metric.kind == "binary":
        n = design.sample_size_binary(mean, mde, alpha, power)
        achieved = design.power_binary(mean, mde, n_per_arm, alpha)
    else:
        n = design.sample_size_mean(mean, sd, mde, alpha, power)
        achieved = design.power_mean(mean, sd, mde, n_per_arm, alpha)
    return Plan(n, mean, sd, achieved)


def analyze(
    client: Client,
    exp: Experiment,
    metrics: dict[str, Metric],
    as_of: datetime | None = None,
    bootstrap: bool = True,
) -> Analysis:
    as_of = as_of or exp.ends_at
    marts.build(client, exp, as_of)
    used = [metrics[n] for n in exp.metric_names]
    arms, multi = load_arms(client, exp.key, _columns(used))
    if set(arms) != {v.name for v in exp.variants} or len(arms) != 2:
        raise ValueError(f"expected control and one treatment with data, got {sorted(arms)}")
    treatment = next(v.name for v in exp.variants if v.name != "control")
    c, t = arms["control"], arms[treatment]
    alpha = exp.design.alpha
    n = {k: len(v[next(iter(v))]) for k, v in arms.items()}

    srm = quality.srm_test(n, {v.name: v.weight for v in exp.variants})
    warnings: list[str] = []
    if srm.failed:
        warnings.append(f"sample ratio mismatch: {srm.describe()}")
    if multi:
        warnings.append(f"{multi} players saw several variants and were excluded")
    if as_of < exp.ends_at:
        warnings.append(
            f"looking early ({as_of:%Y-%m-%d}, the test runs to {exp.ends_at:%Y-%m-%d}): "
            "p-values are not valid for a decision"
        )

    # Covariate balance: randomisation must leave the pre-period equal. A difference there is a
    # sign of broken assignment, never of a treatment effect.
    pre_cols = list(dict.fromkeys(m.pre for m in used if m.pre and m.kind != "ratio"))
    raw_p = [float(estimators.welch_test(c[col], t[col]).p) for col in pre_cols]
    balance = dict(zip(pre_cols, multiple.holm(raw_p) if raw_p else [], strict=True))

    results: list[MetricResult] = []
    for role, names in (("primary", [exp.primary]), ("secondary", exp.secondary)):
        for name in names:
            raw, adjusted = estimate_metric(metrics[name], c, t, alpha)
            res = MetricResult(metrics[name], role, raw, adjusted)
            if metrics[name].kind == "continuous" and bootstrap:
                res.bootstrap_ci = estimators.bootstrap_diff_ci(
                    c[metrics[name].num], t[metrics[name].num], alpha, resamples=1000
                )
            results.append(res)
    secondary = [r for r in results if r.role == "secondary"]
    for r, adj in zip(
        secondary,
        multiple.holm([r.estimate.p for r in secondary]) if secondary else [],
        strict=True,
    ):
        r.p_adjusted = adj
    for g in exp.guardrails:
        raw, adjusted = estimate_metric(metrics[g.metric], c, t, alpha)
        res = MetricResult(metrics[g.metric], "guardrail", raw, adjusted)
        res.guardrail = guardrail_status(metrics[g.metric], c, t, g.max_relative_drop, alpha)
        results.append(res)

    primary = metrics[exp.primary]
    plan = None
    if primary.pre:
        pooled = np.concatenate([c[primary.pre], t[primary.pre]])
        plan = plan_from_data(
            primary, pooled, min(n.values()), exp.design.mde, alpha, exp.design.power
        )
        if plan and min(n.values()) < plan.n_per_arm:
            warnings.append(
                f"underpowered: {min(n.values())} players per arm, {plan.n_per_arm} needed to see "
                f"a {exp.design.mde:.0%} change with {exp.design.power:.0%} power"
            )
    return Analysis(exp, as_of, n, srm, multi, balance, results, plan, warnings)


def z_for_ci(alpha: float) -> float:
    return float(stats.norm.ppf(1 - alpha / 2))


def render(a: Analysis) -> str:
    e = a.experiment
    lines = [
        f"{e.key}: {' '.join(e.hypothesis.split())}",
        f"as of {a.as_of:%Y-%m-%d}" + (" (planned horizon)" if a.at_horizon else " (EARLY LOOK)"),
        "",
        "checks",
        f"  sample ratio   {'FAILED' if a.srm.failed else 'ok'}: {a.srm.describe()}",
        "  pre-period     "
        + (
            "  ".join(f"{k}: p={p:.3f}" for k, p in a.balance.items())
            + (
                "  (balanced)"
                if all(p >= 0.001 for p in a.balance.values())
                else "  IMBALANCED: assignment is suspect"
            )
        ),
        f"  several arms   {a.excluded_multi_variant} players excluded",
    ]
    if a.plan:
        lines.append(
            f"  power          {min(a.arms.values()):,} per arm, {a.plan.n_per_arm:,} needed for "
            f"{e.design.mde:+.0%} -> {a.plan.achieved_power:.0%} power"
        )
    lines += [
        "",
        f"{'':<10}{'metric':<20}{'control':>10}{'treatment':>11}{'change':>9}"
        f"{'95% interval':>20}{'p':>10}  note",
    ]
    for r in a.results:
        est = r.estimate
        note = []
        if est.variance_reduction is not None:
            note.append(f"CUPED -{est.variance_reduction:.0%} var, raw p={r.raw.p:.3g}")
        if r.p_adjusted is not None:
            note.append(f"Holm p={r.p_adjusted:.3g}")
        if r.guardrail:
            note.append(f"guardrail {r.guardrail} (limit -{_margin(e, r):.0%})")
        interval = f"[{est.rel_ci[0]:+.1%}, {est.rel_ci[1]:+.1%}]"
        lines.append(
            f"{r.role:<10}{r.metric.name:<20}{est.mean_control:>10.3f}{est.mean_treatment:>11.3f}"
            f"{est.rel_diff:>+9.1%}{interval:>20}{est.p:>10.3g}  " + "; ".join(note)
        )
    for w in a.warnings:
        lines.append(f"\nWARNING: {w}")
    return "\n".join(lines)


def _margin(e: Experiment, r: MetricResult) -> float:
    return next(g.max_relative_drop for g in e.guardrails if g.metric == r.metric.name)
