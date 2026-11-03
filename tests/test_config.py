from __future__ import annotations

import copy
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from gamma.config import ROOT, Catalog, Experiment, load_catalog

BASE = yaml.safe_load((ROOT / "experiments" / "welcome_bonus.yaml").read_text())


def exp(**changes) -> Experiment:
    d = copy.deepcopy(BASE)
    d.update(changes)
    return Experiment(**d)


def catalog(*experiments: Experiment) -> Catalog:
    return Catalog(metrics=load_catalog().metrics, experiments={e.key: e for e in experiments})


def test_repository_definitions_are_valid():
    cat = load_catalog()
    assert {"welcome_bonus", "cashier_flow", "lobby_layout"} <= set(cat.experiments)
    assert cat.experiments["welcome_bonus"].traffic == 0.5


def test_same_layer_with_shared_buckets_is_refused():
    a = exp(key="exp_a", buckets=[0, 5999])
    b = exp(key="exp_b", buckets=[5000, 9999])
    with pytest.raises(ValidationError, match="share buckets"):
        catalog(a, b)


def test_same_layer_with_disjoint_buckets_is_fine():
    catalog(exp(key="exp_a", buckets=[0, 4999]), exp(key="exp_b", buckets=[5000, 9999]))


def test_shared_buckets_are_fine_when_the_tests_do_not_run_at_the_same_time():
    a = exp(key="exp_a", buckets=[0, 9999])
    b = exp(key="exp_b", buckets=[0, 9999], start="2027-01-01")
    catalog(a, b)


def test_different_layers_may_use_the_same_buckets():
    catalog(
        exp(key="exp_a", layer="one", buckets=[0, 9999]),
        exp(key="exp_b", layer="two", buckets=[0, 9999]),
    )


def test_unknown_metric_is_refused():
    with pytest.raises(ValidationError, match="unknown metric"):
        catalog(exp(primary="vibes"))


def test_primary_metric_cannot_also_be_secondary():
    with pytest.raises(ValidationError, match="also listed as secondary"):
        catalog(exp(secondary=["deposit_conversion"]))


@pytest.mark.parametrize(
    "changes, message",
    [
        ({"buckets": [5000, 20000]}, "buckets must satisfy"),
        ({"buckets": [6000, 5000]}, "buckets must satisfy"),
        (
            {"variants": [{"name": "treatment", "weight": 1}, {"name": "control", "weight": 1}]},
            "first variant",
        ),
        (
            {"variants": [{"name": "control", "weight": 1}, {"name": "control", "weight": 1}]},
            "distinct",
        ),
        ({"variants": [{"name": "control", "weight": 1}]}, "at least two"),
        (
            {"variants": [{"name": "control", "weight": 0}, {"name": "b", "weight": 1}]},
            "greater than 0",
        ),
        ({"hypothesis": "make number go up"}, "hypothesis as a sentence"),
        ({"design": {"mde": 0}}, "greater than 0"),
        ({"surprise": 1}, "Extra inputs"),
    ],
)
def test_invalid_experiments_are_refused(changes, message):
    with pytest.raises(ValidationError, match=message):
        exp(**changes)


def test_file_name_must_match_key(tmp_path: Path):
    (tmp_path / "catalog").mkdir()
    (tmp_path / "experiments").mkdir()
    (tmp_path / "catalog" / "metrics.yaml").write_text(
        (ROOT / "catalog" / "metrics.yaml").read_text()
    )
    (tmp_path / "experiments" / "other_name.yaml").write_text(
        (ROOT / "experiments" / "welcome_bonus.yaml").read_text()
    )
    with pytest.raises(ValueError, match="must match the file name"):
        load_catalog(tmp_path)


def test_ratio_metric_needs_a_denominator():
    from gamma.config import Metric

    with pytest.raises(ValidationError, match="den"):
        Metric(name="m", kind="ratio", num="ggr", better="higher", description="x")
    with pytest.raises(ValidationError, match="den"):
        Metric(
            name="m", kind="continuous", num="ggr", den="stake", better="higher", description="x"
        )


def test_window_dates():
    e = exp()
    assert (e.enrollment_ends_at - e.starts_at).days == 14
    assert (e.ends_at - e.starts_at).days == 21
