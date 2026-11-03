"""The database holds what the platform says it holds.

The mart is SQL; the strongest test of SQL is a second, independent implementation. Here that is
plain Python over the raw rows of a sample of players.
"""

from __future__ import annotations

import shutil
from datetime import timedelta

import pytest

from gamma import marts
from gamma.assign import assign
from gamma.migrate import SCHEMA_DIR, migrate

pytestmark = pytest.mark.e2e


def scalar(client, sql, **params):
    return client.query(sql, parameters=params).result_rows[0][0]


# --- schema ---------------------------------------------------------------------------------


def test_migrations_are_idempotent(client):
    assert migrate(client) == []


def test_an_edited_migration_is_refused(client, tmp_path):
    copy = tmp_path / "schema"
    shutil.copytree(SCHEMA_DIR, copy)
    first = sorted(copy.glob("*.sql"))[0]
    first.write_text(first.read_text() + "\n-- sneaky edit\n")
    with pytest.raises(RuntimeError, match="was changed after it was applied"):
        migrate(client, copy)


# --- assignment -----------------------------------------------------------------------------


@pytest.mark.parametrize("key", ["welcome_bonus", "cashier_flow", "lobby_layout"])
def test_stored_variant_is_the_variant_the_platform_assigns(client, catalog, key):
    """Anyone can recompute who should be in which arm. The data must agree, except for the
    players a crossover bug put in two arms (their first exposure is still the assigned one)."""
    exp = catalog.experiments[key]
    rows = client.query(
        "SELECT player_id, variant FROM mart_user_metrics WHERE experiment = {e:String}",
        parameters={"e": key},
    ).result_rows
    assert rows
    wrong = [(p, v) for p, v in rows if assign(exp, p) != v]
    assert wrong == []


def test_no_player_is_in_two_experiments_of_one_layer(client):
    both = scalar(
        client,
        """
        SELECT count() FROM (
            SELECT player_id FROM exposures
            WHERE experiment IN ('welcome_bonus', 'cashier_flow')
            GROUP BY player_id HAVING uniqExact(experiment) > 1
        )
        """,
    )
    assert both == 0


def test_experiments_in_different_layers_overlap_a_lot(client):
    """Layers exist so that tests do not compete for players; overlapping is the point."""
    both = scalar(
        client,
        """
        SELECT count() FROM (
            SELECT player_id FROM exposures
            WHERE experiment IN ('welcome_bonus', 'lobby_layout')
            GROUP BY player_id HAVING uniqExact(experiment) > 1
        )
        """,
    )
    assert both > 10_000


# --- exposure log ---------------------------------------------------------------------------


def test_exposures_are_logged_more_than_once_and_the_mart_has_one_row_per_player(client):
    rows = scalar(client, "SELECT count() FROM exposures WHERE experiment = 'welcome_bonus'")
    players = scalar(
        client, "SELECT uniqExact(player_id) FROM exposures WHERE experiment = 'welcome_bonus'"
    )
    mart_rows = scalar(
        client, "SELECT count() FROM mart_user_metrics WHERE experiment = 'welcome_bonus'"
    )
    mart_players = scalar(
        client,
        "SELECT uniqExact(player_id) FROM mart_user_metrics WHERE experiment = 'welcome_bonus'",
    )
    assert rows > 1.5 * players
    assert mart_rows == mart_players == players


def test_the_mart_keeps_the_first_exposure(client):
    bad = scalar(
        client,
        """
        SELECT count() FROM mart_user_metrics m
        INNER JOIN (
            SELECT player_id, min(ts) AS first_ts FROM exposures
            WHERE experiment = 'welcome_bonus' GROUP BY player_id
        ) e USING (player_id)
        WHERE m.experiment = 'welcome_bonus' AND m.exposed_at != e.first_ts
        """,
    )
    assert bad == 0


# --- the mart against an independent implementation -----------------------------------------


@pytest.mark.parametrize("key", ["welcome_bonus", "lobby_layout"])
def test_mart_matches_a_python_recomputation(client, catalog, key):
    exp = catalog.experiments[key]
    sample = client.query(
        """
        SELECT player_id, exposed_at, bets, stake, payout, ggr, deposits, deposit_amount, converted,
               pre_bets, pre_stake, pre_ggr, pre_deposit_amount, pre_converted
        FROM mart_user_metrics WHERE experiment = {e:String} ORDER BY cityHash64(player_id) LIMIT 150
        """,
        parameters={"e": key},
    ).result_rows
    assert len(sample) == 150
    ids = [r[0] for r in sample]
    bets = client.query(
        "SELECT player_id, ts, stake_cents, payout_cents FROM bets WHERE player_id IN {ids:Array(UInt64)}",
        parameters={"ids": ids},
    ).result_rows
    deps = client.query(
        "SELECT player_id, ts, amount_cents FROM deposits WHERE player_id IN {ids:Array(UInt64)}",
        parameters={"ids": ids},
    ).result_rows
    win, pre = timedelta(days=exp.window_days), timedelta(days=exp.pre_days)
    checked_nonzero = 0
    for pid, exposed_at, *got in sample:
        exposed_at = exposed_at.replace(tzinfo=None)
        post_b = [
            b
            for b in bets
            if b[0] == pid and exposed_at <= b[1].replace(tzinfo=None) < exposed_at + win
        ]
        pre_b = [
            b
            for b in bets
            if b[0] == pid and exposed_at - pre <= b[1].replace(tzinfo=None) < exposed_at
        ]
        post_d = [
            d
            for d in deps
            if d[0] == pid and exposed_at <= d[1].replace(tzinfo=None) < exposed_at + win
        ]
        pre_d = [
            d
            for d in deps
            if d[0] == pid and exposed_at - pre <= d[1].replace(tzinfo=None) < exposed_at
        ]
        want = [
            len(post_b),
            sum(b[2] for b in post_b) / 100,
            sum(b[3] for b in post_b) / 100,
            sum(b[2] - b[3] for b in post_b) / 100,
            len(post_d),
            sum(d[2] for d in post_d) / 100,
            int(bool(post_d)),
            len(pre_b),
            sum(b[2] for b in pre_b) / 100,
            sum(b[2] - b[3] for b in pre_b) / 100,
            sum(d[2] for d in pre_d) / 100,
            int(bool(pre_d)),
        ]
        assert got == pytest.approx(want, abs=1e-6), (pid, got, want)
        checked_nonzero += bool(post_b) + bool(post_d) + bool(pre_b)
    assert checked_nonzero > 100  # the sample is not trivially all zeros


def test_ggr_is_stake_minus_payout_everywhere(client):
    bad = scalar(
        client, "SELECT count() FROM mart_user_metrics WHERE abs(ggr - (stake - payout)) > 1e-6"
    )
    assert bad == 0


def test_players_without_activity_are_kept_with_zeros(client):
    """A player who did not deposit is a 0 in the conversion metric, not a missing row."""
    inactive = scalar(
        client,
        "SELECT count() FROM mart_user_metrics WHERE experiment = 'welcome_bonus' AND bets = 0 AND deposits = 0",
    )
    total = scalar(
        client, "SELECT count() FROM mart_user_metrics WHERE experiment = 'welcome_bonus'"
    )
    assert 0 < inactive < total


# --- windows ---------------------------------------------------------------------------------


def test_immature_players_are_left_out_of_an_early_look(client, catalog):
    exp = catalog.experiments["welcome_bonus"]
    full = scalar(
        client, "SELECT count() FROM mart_user_metrics WHERE experiment = 'welcome_bonus'"
    )
    as_of = exp.starts_at + timedelta(days=10)
    early = marts.build(client, exp, as_of)
    latest = scalar(
        client, "SELECT max(exposed_at) FROM mart_user_metrics WHERE experiment = 'welcome_bonus'"
    )
    marts.build(client, exp)  # restore the full mart for the other tests
    assert 0 < early < full
    assert latest.replace(tzinfo=None) <= as_of - timedelta(days=exp.window_days)


def test_rebuilding_is_idempotent(client, catalog):
    exp = catalog.experiments["cashier_flow"]
    before = scalar(
        client, "SELECT count() FROM mart_user_metrics WHERE experiment = 'cashier_flow'"
    )
    assert marts.build(client, exp) == before
    assert marts.build(client, exp) == before


# --- the world holds what the scenario put into it -----------------------------------------


def arm(client, key, variant, column):
    return float(
        scalar(
            client,
            f"SELECT avg({column}) FROM mart_user_metrics WHERE experiment = {{e:String}} AND variant = {{v:String}}",
            e=key,
            v=variant,
        )
    )


def test_the_real_effect_points_the_right_way(client):
    control = arm(client, "welcome_bonus", "control", "converted")
    treatment = arm(client, "welcome_bonus", "treatment", "converted")
    lift = treatment / control - 1
    # the true lift of the deposit rate is +12%; conversion saturates, so less, and 40k
    # players leave a wide interval. The statistics in the next step make this rigorous.
    assert 0.0 < lift < 0.20, lift


def test_a_split_without_an_effect_does_not_move_much(client):
    control = arm(client, "lobby_layout", "control", "bets")
    treatment = arm(client, "lobby_layout", "treatment", "bets")
    assert abs(treatment / control - 1) < 0.10


def test_injected_logging_bug_is_visible_in_the_counts(client):
    def players(key, variant):
        return scalar(
            client,
            "SELECT count() FROM mart_user_metrics WHERE experiment = {e:String} AND variant = {v:String}",
            e=key,
            v=variant,
        )

    clean = players("welcome_bonus", "treatment") / players("welcome_bonus", "control")
    broken = players("cashier_flow", "treatment") / players("cashier_flow", "control")
    assert 0.95 < clean < 1.05, clean
    assert broken < 0.93, broken  # ~12% of the treatment arm vanished


def test_injected_crossover_is_flagged_only_where_it_was_injected(client):
    def multi(key):
        return scalar(
            client,
            "SELECT countIf(n_variants > 1) FROM mart_user_metrics WHERE experiment = {e:String}",
            e=key,
        )

    assert multi("lobby_layout") > 50
    assert multi("welcome_bonus") == 0
    assert multi("cashier_flow") == 0
