"""Sample size and duration, from the pre-period of the people already in the experiment."""

from __future__ import annotations

import numpy as np
from clickhouse_connect.driver.client import Client

from . import marts
from .analyze import load_arms
from .config import Experiment, Metric
from .stats import design


def render(client: Client, exp: Experiment, metrics: dict[str, Metric], mde: float | None) -> str:
    mde = mde or exp.design.mde
    marts.build(client, exp)  # the full-horizon mart, not whatever an early look left behind
    a, p = exp.design.alpha, exp.design.power
    cols = [c for n in exp.metric_names for c in (metrics[n].num, metrics[n].pre) if c]
    arms, _ = load_arms(client, exp.key, [*dict.fromkeys(cols), "converted"])
    n_all = sum(len(v["converted"]) for v in arms.values())
    daily = n_all / exp.enrollment_days
    lines = [
        f"{exp.key}: alpha {a}, power {p:.0%}, detect a {mde:+.1%} relative change",
        f"baselines come from the {exp.pre_days} days before exposure; "
        f"{daily:,.0f} players enter per day",
        "",
        f"{'metric':<20}{'baseline':>10}{'sd':>9}{'per arm':>12}{'with CUPED':>14}{'days':>9}",
    ]
    for name in exp.metric_names:
        m = metrics[name]
        if not m.pre:
            lines.append(
                f"{name:<20}{'no pre-period column (ratio metric), plan from an earlier test':>48}"
            )
            continue
        x = np.concatenate([v[m.pre] for v in arms.values()])
        mean, sd = float(x.mean()), float(x.std(ddof=1))
        if m.kind == "binary":
            n = design.sample_size_binary(mean, mde, a, p)
            n_cuped = n  # a 0/1 pre-period rarely explains much
        else:
            n = design.sample_size_mean(mean, sd, mde, a, p)
            y = np.concatenate([v[m.num] for v in arms.values()])
            rho2 = float(np.corrcoef(x, y)[0, 1] ** 2)
            n_cuped = design.sample_size_mean(mean, sd, mde, a, p, variance_reduction=rho2)
        days = 2 * n / daily
        lines.append(f"{name:<20}{mean:>10.3f}{sd:>9.3f}{n:>12,}{n_cuped:>14,}{days:>9.1f}")
    lines.append("")
    lines.append(
        "days = how long the enrollment must run to reach `per arm` in both arms at this rate; "
        f"this test enrolls for {exp.enrollment_days}."
    )
    return "\n".join(lines)
