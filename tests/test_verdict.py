"""The decision rules, on analyses built from synthetic data with a chosen truth."""

from __future__ import annotations

from datetime import timedelta

import numpy as np
import pytest

from gamma import analyze as analysis
from gamma import report, verdict
from gamma.config import load_catalog
from gamma.stats import quality

CAT = load_catalog()
EXP = CAT.experiments["welcome_bonus"]  # primary deposit_conversion, guardrail stake_per_player


def arms(n: int, lift: float, stake_lift: float = 0.0, stake_sd: float = 5.0, seed: int = 3):
    """Control and treatment arrays with the columns the welcome_bonus metrics need."""
    rng = np.random.default_rng(seed)

    def one(conv_p, stake_mean):
        stake = np.clip(rng.normal(stake_mean, stake_sd, n), 0, None)
        return {
            "converted": (rng.random(n) < conv_p).astype(float),
            "pre_converted": (rng.random(n) < 0.3).astype(float),
            "stake": stake,
            "pre_stake": stake * 0 + rng.normal(stake_mean, stake_sd, n),
            "deposit_amount": rng.exponential(50, n),
            "pre_deposit_amount": rng.exponential(50, n),
            "bets": rng.poisson(6, n).astype(float),
            "pre_bets": rng.poisson(6, n).astype(float),
            "ggr": rng.normal(3, 90, n),
            "pre_ggr": rng.normal(3, 90, n),
        }

    return one(0.30, 60.0), one(0.30 * (1 + lift), 60.0 * (1 + stake_lift))


def make(
    lift=0.0, n=60_000, stake_lift=0.0, stake_sd=5.0, srm=False, early=False, balance=0.5, seed=3
) -> analysis.Analysis:
    c, t = arms(n, lift, stake_lift, stake_sd, seed)
    results = []
    for role, names in (("primary", [EXP.primary]), ("secondary", EXP.secondary)):
        for name in names:
            raw, adj = analysis.estimate_metric(CAT.metrics[name], c, t, 0.05)
            results.append(analysis.MetricResult(CAT.metrics[name], role, raw, adj, p_adjusted=0.5))
    for g in EXP.guardrails:
        raw, adj = analysis.estimate_metric(CAT.metrics[g.metric], c, t, 0.05)
        res = analysis.MetricResult(CAT.metrics[g.metric], "guardrail", raw, adj)
        res.guardrail = analysis.guardrail_status(
            CAT.metrics[g.metric], c, t, g.max_relative_drop, 0.05
        )
        results.append(res)
    counts = {"control": n, "treatment": n - (n // 10 if srm else 0)}
    return analysis.Analysis(
        experiment=EXP,
        as_of=EXP.ends_at - (timedelta(days=5) if early else timedelta(0)),
        arms=counts,
        srm=quality.srm_test(counts, {"control": 1, "treatment": 1}),
        excluded_multi_variant=0,
        balance={"pre_converted": balance},
        results=results,
        plan=None,
    )


def test_a_clear_win_with_safe_guardrails_ships():
    v = verdict.decide(make(lift=0.10))
    assert v.decision == verdict.SHIP


def test_sample_ratio_mismatch_overrides_a_win():
    v = verdict.decide(make(lift=0.10, srm=True))
    assert v.decision == verdict.INVALID
    assert "sample ratio" in " ".join(v.reasons)


def test_imbalanced_pre_period_is_invalid():
    assert verdict.decide(make(lift=0.10, balance=1e-6)).decision == verdict.INVALID


def test_an_early_look_waits_even_when_significant():
    assert verdict.decide(make(lift=0.10, early=True)).decision == verdict.WAIT


def test_a_broken_guardrail_blocks_a_win():
    v = verdict.decide(make(lift=0.10, stake_lift=-0.20))
    assert v.decision == verdict.DO_NOT_SHIP
    assert "stake_per_player" in v.headline


def test_an_undecided_guardrail_is_a_hold_not_a_pass():
    # very noisy stake: the interval spans the margin
    v = verdict.decide(make(lift=0.10, n=3000, stake_sd=400.0))
    assert v.decision == verdict.HOLD


def test_a_significant_loss_does_not_ship():
    assert verdict.decide(make(lift=-0.10)).decision == verdict.DO_NOT_SHIP


def test_a_tight_null_stops_the_experiment():
    v = verdict.decide(make(lift=0.0, n=200_000))
    assert v.decision == verdict.NO_EFFECT
    assert "rules out" in " ".join(v.reasons)


def test_a_wide_null_is_inconclusive():
    assert verdict.decide(make(lift=0.0, n=1500, seed=1)).decision == verdict.INCONCLUSIVE


def test_a_metric_where_lower_is_better_reads_the_other_way():
    a = make(lift=0.10)
    primary = next(r for r in a.results if r.role == "primary")
    primary.metric = primary.metric.model_copy(update={"better": "lower"})
    assert verdict.decide(a).decision == verdict.DO_NOT_SHIP


@pytest.mark.parametrize("lift", [0.10, 0.0])
def test_the_report_renders_for_any_decision(lift):
    a = make(lift=lift)
    text = report.render(a, verdict.decide(a), [])
    assert text.startswith("# welcome_bonus: ")
    assert "## Results" in text and "stake_per_player" in text
