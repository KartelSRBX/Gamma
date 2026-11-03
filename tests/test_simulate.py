from __future__ import annotations

import numpy as np
import pytest
from pydantic import ValidationError

from gamma.config import load_catalog
from gamma.simulate import Scenario, load_scenario, simulate

CAT = load_catalog()


def small(players: int = 6000, **changes) -> Scenario:
    s = load_scenario()
    s.players = players
    for k, v in changes.items():
        setattr(s, k, v)
    return s


@pytest.fixture(scope="module")
def data():
    return simulate(small(), CAT)


def test_same_seed_gives_identical_data(data):
    again = simulate(small(), CAT)
    for table in ("exposures", "bets", "deposits"):
        for col, values in getattr(data, table).items():
            assert np.array_equal(values, getattr(again, table)[col]), (table, col)


def test_other_seed_gives_other_data(data):
    other = simulate(small(seed=1), CAT)
    assert not np.array_equal(data.bets["stake_cents"][:1000], other.bets["stake_cents"][:1000])


def test_return_to_player_is_about_96_percent():
    big = simulate(small(40000), CAT)
    rtp = big.bets["payout_cents"].sum() / big.bets["stake_cents"].sum()
    assert 0.93 < rtp < 0.99, rtp


def test_money_is_positive_integers_cents(data):
    assert data.bets["stake_cents"].min() >= 10
    assert data.deposits["amount_cents"].min() >= 500
    assert data.bets["stake_cents"].dtype == np.uint32


def test_every_logged_exposure_is_inside_the_enrollment_period(data):
    for key, exp in CAT.experiments.items():
        sel = data.exposures["experiment"] == key
        ts = data.exposures["ts"][sel]
        start = np.datetime64(exp.starts_at, "s").astype(np.int64)
        end = np.datetime64(exp.ends_at, "s").astype(np.int64)
        assert ts.min() >= start
        assert ts.max() < end


def test_exposures_are_logged_repeatedly(data):
    sel = data.exposures["experiment"] == "welcome_bonus"
    pids = data.exposures["player_id"][sel]
    assert len(pids) > 1.5 * len(set(pids.tolist()))


def test_dropped_exposure_fault_removes_players_of_one_arm_and_device():
    clean = simulate(small(faults=[]), CAT)
    faulty = simulate(small(), CAT)

    def count(d, variant):
        sel = (d.exposures["experiment"] == "cashier_flow") & (d.exposures["variant"] == variant)
        return len(set(d.exposures["player_id"][sel].tolist()))

    assert count(faulty, "control") == count(clean, "control")
    lost = 1 - count(faulty, "treatment") / count(clean, "treatment")
    # 35% of the ios players (35% of players) are not logged: about 12% of the arm
    assert 0.09 < lost < 0.15, lost


def test_two_real_effects_are_refused():
    s = load_scenario().model_dump()
    s["truth"]["cashier_flow"]["treatment"] = {"deposit_rate": 1.2}
    with pytest.raises(ValidationError, match="only one experiment"):
        Scenario(**s)


def test_fault_for_unknown_experiment_is_refused():
    s = small()
    s.faults = [*s.faults, s.faults[0].model_copy(update={"experiment": "nope"})]
    with pytest.raises(ValueError, match="not in `truth`"):
        simulate(s, CAT)


def test_the_effect_applies_only_after_exposure():
    """Deposits per player-day rise in treatment after exposure and not before it."""
    s = small(60000)
    s.truth["welcome_bonus"]["treatment"].deposit_rate = 2.0
    d = simulate(s, CAT)
    sel = d.exposures["experiment"] == "welcome_bonus"
    pid, var, ts = (d.exposures[c][sel] for c in ("player_id", "variant", "ts"))
    order = np.lexsort((ts, pid))
    pid, var, ts = pid[order], var[order], ts[order]
    first = np.r_[True, pid[1:] != pid[:-1]]
    pid, var, ts = pid[first], var[first], ts[first]
    exposed_at = dict(zip(pid.tolist(), ts.tolist(), strict=True))
    arm = dict(zip(pid.tolist(), var.tolist(), strict=True))
    before = {"control": 0.0, "treatment": 0.0}
    after = {"control": 0.0, "treatment": 0.0}
    days_before = {"control": 0.0, "treatment": 0.0}
    days_after = {"control": 0.0, "treatment": 0.0}
    t_end = np.datetime64(CAT.experiments["welcome_bonus"].ends_at, "s").astype(np.int64)
    for p, t in exposed_at.items():
        days_before[arm[p]] += 14
        days_after[arm[p]] += (t_end - t) / 86400
    for p, t in zip(d.deposits["player_id"].tolist(), d.deposits["ts"].tolist(), strict=True):
        if p in exposed_at:
            (before if t < exposed_at[p] else after)[arm[p]] += 1
    # rate ratio treatment / control, before and after
    pre_ratio = (before["treatment"] / days_before["treatment"]) / (
        before["control"] / days_before["control"]
    )
    post_ratio = (after["treatment"] / days_after["treatment"]) / (
        after["control"] / days_after["control"]
    )
    assert 0.9 < pre_ratio < 1.1, pre_ratio
    assert 1.8 < post_ratio < 2.2, post_ratio
