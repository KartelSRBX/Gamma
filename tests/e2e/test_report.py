"""Verdicts on the simulated world, and the results tables that dashboards read."""

from __future__ import annotations

import pytest

from gamma import analyze as analysis
from gamma import report, segments, store, verdict

pytestmark = pytest.mark.e2e


@pytest.fixture(scope="module")
def runs(client, catalog):
    out = {}
    for key, exp in catalog.experiments.items():
        a = analysis.analyze(client, exp, catalog.metrics, bootstrap=False)
        segs = segments.by_dimension(client, exp, catalog.metrics[exp.primary])
        out[key] = (a, verdict.decide(a), segs)
    return out


def test_the_real_win_ships(runs):
    assert runs["welcome_bonus"][1].decision == verdict.SHIP


def test_the_test_with_the_logging_bug_is_invalid(runs):
    v = runs["cashier_flow"][1]
    assert v.decision == verdict.INVALID
    assert "sample ratio" in " ".join(v.reasons)


def test_the_null_test_is_a_clear_no_effect(runs):
    v = runs["lobby_layout"][1]
    assert v.decision == verdict.NO_EFFECT
    assert "rules out" in " ".join(v.reasons)


def test_segments_cover_every_dimension_and_are_adjusted(runs):
    segs = runs["welcome_bonus"][2]
    assert {s.dimension for s in segs} == {"segment", "device", "country"}
    assert all(s.p_adjusted >= s.estimate.p for s in segs)
    by_segment = [s for s in segs if s.dimension == "segment"]
    assert sum(s.estimate.n_control for s in by_segment) == runs["welcome_bonus"][0].arms["control"]


def test_the_report_names_the_decision_and_every_metric(runs):
    a, v, segs = runs["welcome_bonus"]
    text = report.render(a, v, segs)
    assert text.startswith("# welcome_bonus: SHIP")
    for r in a.results:
        assert f"`{r.metric.name}`" in text
    assert "exploratory" in text


def test_results_are_stored_and_the_views_show_only_the_latest_run(client, runs):
    a, v, segs = runs["welcome_bonus"]
    first = store.save(client, a, v, segs)
    second = store.save(client, a, v, segs)
    assert first != second
    stored = client.query(
        "SELECT count(DISTINCT run_id) FROM experiment_runs WHERE experiment = 'welcome_bonus'"
    ).result_rows[0][0]
    assert stored >= 2
    latest = client.query(
        "SELECT DISTINCT run_id FROM v_latest_results WHERE experiment = 'welcome_bonus'"
    ).result_rows
    assert [str(r[0]) for r in latest] == [str(second)]
    row = client.query(
        "SELECT decision, rel_diff, rel_ci_low, rel_ci_high FROM v_latest_results "
        "WHERE experiment = 'welcome_bonus' AND role = 'primary'"
    ).result_rows[0]
    assert row[0] == "SHIP"
    assert row[2] < row[1] < row[3]
