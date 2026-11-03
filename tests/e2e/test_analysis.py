"""The analysis, run on the simulated world, must reach the conclusions the scenario implies."""

from __future__ import annotations

from datetime import timedelta

import pytest

from gamma import analyze as analysis

pytestmark = pytest.mark.e2e


@pytest.fixture(scope="module")
def results(client, catalog):
    return {
        key: analysis.analyze(client, exp, catalog.metrics, bootstrap=False)
        for key, exp in catalog.experiments.items()
    }


def by_name(a, name):
    return next(r for r in a.results if r.metric.name == name)


def test_a_real_lift_is_found_with_an_interval_around_it(results):
    a = results["welcome_bonus"]
    assert a.valid and a.warnings == []
    primary = by_name(a, "deposit_conversion").estimate
    assert primary.p < 0.001
    # the deposit rate was raised by 6%; the share of players with a deposit rises less, because
    # a rate saturates when converted to a probability of at least one deposit
    assert 0.01 < primary.rel_ci[0] < primary.rel_diff < primary.rel_ci[1] < 0.09


def test_secondary_metrics_are_adjusted_for_multiplicity(results):
    a = results["welcome_bonus"]
    secondary = [r for r in a.results if r.role == "secondary"]
    assert len(secondary) == 3
    assert all(r.p_adjusted >= r.estimate.p for r in secondary)
    assert any(r.p_adjusted > r.estimate.p for r in secondary)


def test_cuped_sees_what_the_raw_estimate_cannot(results):
    """+2% bets with a heavy-tailed metric: invisible raw, unmistakable after CUPED."""
    r = by_name(results["welcome_bonus"], "bets_per_player")
    assert r.raw.p > 0.05
    assert r.estimate.p < 1e-6
    assert r.estimate.variance_reduction > 0.8
    assert r.estimate.rel_ci[0] > 0


def test_guardrail_that_cannot_be_decided_is_not_a_pass(results):
    """GGR is too noisy at this size: the interval spans tens of percent."""
    r = by_name(results["cashier_flow"], "ggr_per_player")
    assert r.guardrail == "inconclusive"
    assert r.estimate.rel_ci[1] - r.estimate.rel_ci[0] > 0.5


def test_guardrail_with_a_tight_interval_passes(results):
    assert by_name(results["welcome_bonus"], "stake_per_player").guardrail == "ok"
    assert by_name(results["lobby_layout"], "avg_stake").guardrail == "ok"


def test_the_logging_bug_makes_the_test_invalid(results):
    a = results["cashier_flow"]
    assert a.srm.failed and a.srm.p < 1e-30
    assert not a.valid
    assert any("sample ratio mismatch" in w for w in a.warnings)


def test_a_null_experiment_is_not_significant_and_crossover_players_are_excluded(results):
    a = results["lobby_layout"]
    assert a.valid
    assert by_name(a, "bets_per_player").estimate.p > 0.01
    assert a.excluded_multi_variant > 100
    assert any("several variants" in w for w in a.warnings)


def test_balanced_pre_period_where_assignment_is_honest(results):
    for key in ("welcome_bonus", "lobby_layout"):
        assert all(p > 0.001 for p in results[key].balance.values())


def test_an_early_look_is_flagged(client, catalog):
    exp = catalog.experiments["welcome_bonus"]
    early = analysis.analyze(
        client, exp, catalog.metrics, exp.starts_at + timedelta(days=10), False
    )
    try:
        assert not early.at_horizon
        assert any("looking early" in w for w in early.warnings)
        full = analysis.analyze(client, exp, catalog.metrics, bootstrap=False)
        assert sum(early.arms.values()) < 0.85 * sum(full.arms.values())
    finally:
        from gamma import marts

        marts.build(client, exp)
