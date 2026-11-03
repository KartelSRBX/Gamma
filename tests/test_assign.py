from __future__ import annotations

import numpy as np
from scipy import stats

from gamma.assign import assign, bucket
from gamma.config import BUCKETS, Experiment

N = 60_000


def make(key: str, layer: str = "promo", buckets=(0, 9999), weights=(50, 50)) -> Experiment:
    return Experiment(
        key=key,
        layer=layer,
        owner="test",
        hypothesis="a long enough sentence so that the hypothesis validator is satisfied",
        start="2026-09-01",
        enrollment_days=14,
        window_days=7,
        pre_days=14,
        buckets=list(buckets),
        variants=[
            {"name": "control", "weight": weights[0]},
            {"name": "treatment", "weight": weights[1]},
        ],
        primary="deposit_conversion",
        design={"mde": 0.05},
    )


def test_assignment_is_a_pure_function():
    e = make("exp_a")
    assert [assign(e, p) for p in range(1000)] == [assign(e, p) for p in range(1000)]


def test_buckets_are_uniform():
    counts = np.bincount([bucket("promo", p) for p in range(N)], minlength=BUCKETS)
    # 6 players per bucket on average; a hash that clusters would blow this up
    chi2, p = stats.chisquare(counts)
    assert p > 0.001, (chi2, p)


def test_split_follows_the_weights():
    for weights, share in (((50, 50), 0.5), ((90, 10), 0.1), ((20, 80), 0.8)):
        e = make("exp_a", weights=weights)
        got = np.mean([assign(e, p) == "treatment" for p in range(N)])
        se = (share * (1 - share) / N) ** 0.5
        assert abs(got - share) < 4 * se, (weights, got)


def test_traffic_follows_the_bucket_range():
    e = make("exp_a", buckets=(0, 2499))
    got = np.mean([assign(e, p) is not None for p in range(N)])
    assert abs(got - 0.25) < 0.01


def test_same_layer_disjoint_ranges_never_share_a_player():
    a = make("exp_a", buckets=(0, 4999))
    b = make("exp_b", buckets=(5000, 9999))
    both = [p for p in range(N) if assign(a, p) and assign(b, p)]
    assert both == []
    assert sum(1 for p in range(N) if assign(a, p) or assign(b, p)) == N


def crosstab(a: Experiment, b: Experiment):
    table = np.zeros((2, 2))
    for p in range(N):
        va, vb = assign(a, p), assign(b, p)
        if va and vb:
            table[int(va == "treatment"), int(vb == "treatment")] += 1
    return table


def test_experiments_in_different_layers_are_independent():
    table = crosstab(make("exp_a", layer="one"), make("exp_b", layer="two"))
    assert table.sum() == N
    assert stats.chi2_contingency(table)[1] > 0.001


def test_experiments_in_one_layer_get_independent_variants_thanks_to_the_salt():
    # Same layer and same buckets (allowed when they run at different times): without the
    # per-experiment salt the same players would be treatment both times.
    table = crosstab(make("exp_a"), make("exp_b"))
    assert stats.chi2_contingency(table)[1] > 0.001
    assert table[1, 1] < 0.3 * N


def test_known_values_do_not_change():
    # Changing the hash re-randomises every running experiment. This test is the alarm.
    e = make("exp_a")
    assert [assign(e, p) for p in (1, 2, 3, 4, 5, 6, 7, 8)] == [
        "control",
        "treatment",
        "treatment",
        "control",
        "treatment",
        "treatment",
        "treatment",
        "treatment",
    ]
