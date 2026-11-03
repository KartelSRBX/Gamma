"""From an analysis to a decision, by rules that can be read in one screen.

The rules are ordered by what must be true before the next one is worth asking:

1. Is the data trustworthy?      no  -> INVALID    (do not read any number)
2. Is it the planned horizon?    no  -> WAIT       (p-values of an early look are not valid)
3. Is a guardrail broken?        yes -> DO NOT SHIP
4. Is the primary metric moved?  yes, the right way  -> SHIP, if every guardrail is shown safe
                                                         (an undecided guardrail is HOLD)
                                 yes, the wrong way  -> DO NOT SHIP
                                 no, and the interval rules out the planned effect -> NO EFFECT
                                 no, and it does not -> INCONCLUSIVE
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .analyze import Analysis, MetricResult

SHIP, DO_NOT_SHIP, INVALID, WAIT, HOLD, NO_EFFECT, INCONCLUSIVE = (
    "SHIP",
    "DO_NOT_SHIP",
    "INVALID",
    "WAIT",
    "HOLD",
    "NO_EFFECT",
    "INCONCLUSIVE",
)


@dataclass
class Verdict:
    decision: str
    headline: str
    reasons: list[str] = field(default_factory=list)
    next_steps: list[str] = field(default_factory=list)


def _pct(x: float) -> str:
    return f"{x:+.1%}"


def decide(a: Analysis) -> Verdict:
    exp = a.experiment
    primary = next(r for r in a.results if r.role == "primary")
    guardrails = [r for r in a.results if r.role == "guardrail"]
    est = primary.estimate
    good = est.rel_diff > 0 if primary.metric.better == "higher" else est.rel_diff < 0
    interval = f"{_pct(est.rel_ci[0])} to {_pct(est.rel_ci[1])}"
    facts = [
        f"`{primary.metric.name}` changed {_pct(est.rel_diff)} (95% interval {interval}, p = {est.p:.2g})"
    ]

    # 1. data quality
    broken: list[str] = []
    if a.srm.failed:
        broken.append(f"sample ratio mismatch: {a.srm.describe()}")
    bad_balance = {k: p for k, p in a.balance.items() if p < 0.001}
    if bad_balance:
        broken.append(
            "the pre-period differs between arms ("
            + ", ".join(f"{k}: adjusted p = {p:.2g}" for k, p in bad_balance.items())
            + ")"
        )
    if broken:
        return Verdict(
            INVALID,
            "The data cannot be trusted, so no result is reported as a finding.",
            [*broken, "Estimates are shown below for diagnosis only: " + facts[0]],
            [
                "Find why players are missing or unevenly assigned (logging of the exposure event,"
                " bot filters, redirects, a platform that does not support the variant).",
                "Fix it and restart the experiment; do not correct the numbers afterwards.",
            ],
        )

    # 2. horizon
    if not a.at_horizon:
        return Verdict(
            WAIT,
            f"The planned horizon ({exp.ends_at:%Y-%m-%d}) is not reached.",
            [
                f"Analysis date {a.as_of:%Y-%m-%d}; a fixed-horizon test must be read once, at the end."
                " Looking early and acting on a significant result makes false positives several"
                " times more likely.",
                "For now: " + facts[0],
            ],
            ["Wait for the horizon, or plan the looks in advance (`gamma.stats.sequential`)."],
        )

    reasons = list(facts)
    if a.excluded_multi_variant:
        reasons.append(
            f"{a.excluded_multi_variant} players saw several variants and were excluded"
            " (a randomisation bug worth fixing, small enough not to change the conclusion)."
        )

    # 3. guardrails
    violated = [g for g in guardrails if g.guardrail == "violated"]
    undecided = [g for g in guardrails if g.guardrail == "inconclusive"]
    for g in guardrails:
        reasons.append(_guardrail_line(g))
    if violated:
        names = ", ".join(f"`{g.metric.name}`" for g in violated)
        return Verdict(
            DO_NOT_SHIP,
            f"A guardrail is broken: {names}.",
            reasons,
            ["Do not ship, whatever the primary metric did. Understand the mechanism first."],
        )

    # 4. the primary metric
    significant = est.p < exp.design.alpha
    if significant and good:
        if undecided:
            names = ", ".join(f"`{g.metric.name}`" for g in undecided)
            return Verdict(
                HOLD,
                f"The primary metric improved, but {names} cannot be shown safe.",
                reasons,
                [
                    "An owner decides whether to accept the risk, or the test runs longer."
                    " An inconclusive guardrail is not a pass.",
                ],
            )
        if est.rel_ci[0] < exp.design.mde:
            reasons.append(
                f"The lower end of the interval ({_pct(est.rel_ci[0])}) is below the {exp.design.mde:.0%}"
                " the test was planned to detect: the effect is real but may be smaller than hoped."
            )
        return Verdict(
            SHIP,
            "Ship: the primary metric moved the right way and every guardrail is safe.",
            reasons,
            [
                "Roll out gradually and watch the guardrails; keep a small holdout to confirm the effect."
            ],
        )
    if significant and not good:
        return Verdict(
            DO_NOT_SHIP,
            "The primary metric moved the wrong way.",
            reasons,
            ["Do not ship. Check whether the change broke something rather than failing to help."],
        )
    upper = est.rel_ci[1] if primary.metric.better == "higher" else -est.rel_ci[0]
    if upper < exp.design.mde:
        reasons.append(
            f"The interval rules out an improvement of {exp.design.mde:.0%} or more: at most {_pct(upper)}."
        )
        return Verdict(
            NO_EFFECT,
            "No effect worth shipping.",
            reasons,
            ["Stop the experiment and record the result: a clear null is information."],
        )
    reasons.append(
        f"The interval still includes an improvement of {exp.design.mde:.0%}; the data cannot tell."
    )
    return Verdict(
        INCONCLUSIVE,
        "Inconclusive: no significant change, and an effect of the planned size is not ruled out.",
        reasons,
        ["Extend enrollment (see `gamma plan`), or accept that the effect is below what matters."],
    )


def _guardrail_line(g: MetricResult) -> str:
    est = g.estimate
    return (
        f"guardrail `{g.metric.name}`: {g.guardrail} (change {_pct(est.rel_diff)}, "
        f"interval {_pct(est.rel_ci[0])} to {_pct(est.rel_ci[1])})"
    )
