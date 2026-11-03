"""The experiment report: one page that a product manager can act on and an analyst can audit."""

from __future__ import annotations

from .analyze import Analysis, MetricResult
from .segments import SegmentResult
from .verdict import Verdict

LABEL = {
    "SHIP": "SHIP",
    "DO_NOT_SHIP": "DO NOT SHIP",
    "INVALID": "INVALID, DO NOT READ",
    "WAIT": "WAIT",
    "HOLD": "HOLD",
    "NO_EFFECT": "NO EFFECT, STOP",
    "INCONCLUSIVE": "INCONCLUSIVE",
}


def _pct(x: float) -> str:
    return f"{x:+.1%}"


def _num(x: float) -> str:
    return f"{x:,.3f}" if abs(x) < 100 else f"{x:,.1f}"


def _p(x: float) -> str:
    return f"{x:.2g}" if x < 0.001 else f"{x:.3f}"


def _row(r: MetricResult) -> str:
    e = r.estimate
    note = []
    if r.p_adjusted is not None:
        note.append(f"Holm p = {_p(r.p_adjusted)}")
    if e.variance_reduction is not None:
        note.append(f"CUPED removed {e.variance_reduction:.0%} of the variance")
    if r.guardrail:
        note.append(f"guardrail **{r.guardrail}**")
    if r.bootstrap_ci is not None:
        note.append(
            f"raw bootstrap interval of the difference (no CUPED) [{r.bootstrap_ci[0]:+.2f}, {r.bootstrap_ci[1]:+.2f}]"
        )
    return (
        f"| `{r.metric.name}` | {_num(e.mean_control)} | {_num(e.mean_treatment)} | {_pct(e.rel_diff)} "
        f"| {_pct(e.rel_ci[0])} to {_pct(e.rel_ci[1])} | {_p(e.p)} | {e.method} | {'; '.join(note)} |"
    )


def render(a: Analysis, v: Verdict, segments: list[SegmentResult]) -> str:
    e = a.experiment
    out = [
        f"# {e.key}: {LABEL[v.decision]}",
        "",
        f"> {' '.join(e.hypothesis.split())}",
        "",
        f"Owner: {e.owner}. Layer `{e.layer}`, {e.traffic:.0%} of its traffic. Enrollment "
        f"{e.start:%Y-%m-%d} to {e.enrollment_ends_at:%Y-%m-%d}, each player followed for "
        f"{e.window_days} days after the first exposure. Analysis date {a.as_of:%Y-%m-%d}"
        + (" (planned horizon)." if a.at_horizon else " (**early look**)."),
        "",
        f"## Decision: {LABEL[v.decision]}",
        "",
        f"**{v.headline}**",
        "",
        *[f"- {r}" for r in v.reasons],
        "",
        "Next: " + " ".join(v.next_steps),
        "",
        "## Is the data trustworthy?",
        "",
        "| Check | Result |",
        "| --- | --- |",
        f"| Sample ratio ({', '.join(f'{k} {n:,}' for k, n in a.arms.items())}) | "
        f"{'**FAILED**' if a.srm.failed else 'ok'}, chi-square p = {a.srm.p:.3g} |",
        "| Pre-period balance (Holm-adjusted) | "
        + ", ".join(f"`{k}` p = {_p(p)}" for k, p in a.balance.items())
        + (" · ok" if all(p >= 0.001 for p in a.balance.values()) else " · **IMBALANCED**")
        + " |",
        f"| Players who saw several variants | {a.excluded_multi_variant:,} excluded |",
    ]
    if a.plan:
        out.append(
            f"| Power | {min(a.arms.values()):,} players per arm; {a.plan.n_per_arm:,} needed to see "
            f"{e.design.mde:+.0%} of `{e.primary}` with {e.design.power:.0%} power "
            f"(achieved {a.plan.achieved_power:.0%}) |"
        )
    out += [
        "",
        "## Results",
        "",
        "Change is relative to control. Intervals are 95%. The primary metric is tested alone at "
        f"alpha = {e.design.alpha}; secondary metrics are adjusted together with Holm; guardrails are "
        "one-sided non-inferiority tests against the allowed drop.",
        "",
        "| Metric | Control | Treatment | Change | 95% interval | p | Method | Notes |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for role, title in (
        ("primary", "Primary"),
        ("secondary", "Secondary"),
        ("guardrail", "Guardrails"),
    ):
        rows = [r for r in a.results if r.role == role]
        if rows:
            out.append(f"| **{title}** | | | | | | | |")
            out += [_row(r) for r in rows]
    if segments:
        out += [
            "",
            f"## Where is the effect? (exploratory, `{e.primary}`)",
            "",
            "Segments are leads for the next experiment, not grounds to ship to one of them. "
            "Holm adjusts the segments of each dimension together.",
            "",
            "| Dimension | Value | Players (control / treatment) | Change | 95% interval | Holm p |",
            "| --- | --- | --- | --- | --- | --- |",
        ]
        for s in segments:
            est = s.estimate
            out.append(
                f"| {s.dimension} | {s.value} | {est.n_control:,} / {est.n_treatment:,} | "
                f"{_pct(est.rel_diff)} | {_pct(est.rel_ci[0])} to {_pct(est.rel_ci[1])} | {_p(s.p_adjusted)} |"
            )
    if a.warnings:
        out += ["", "## Warnings", "", *[f"- {w}" for w in a.warnings]]
    seen: dict[str, str] = {}
    for r in a.results:
        seen[r.metric.name] = r.metric.description
    out += ["", "## Metric definitions", "", *[f"- `{k}`: {d}" for k, d in seen.items()], ""]
    return "\n".join(out)
