"""Per-player metrics for one experiment, computed in ClickHouse.

The unit of analysis is the player, because that is what was randomised. Everything is measured
from the player's FIRST exposure: a post-exposure window of `window_days` and a pre-exposure
window of `pre_days` (used later for variance reduction).

Players whose window is not complete at `as_of` are left out. Including them would count a
player who was exposed an hour ago as a player who did not deposit, which biases every rate
down, and more so for the arm that happened to be exposed later.
"""

from __future__ import annotations

from datetime import UTC, datetime

from clickhouse_connect.driver.client import Client

from .config import Experiment

BUILD_SQL = """
INSERT INTO mart_user_metrics
WITH first_exposure AS (
    SELECT
        player_id,
        argMin(variant, ts) AS arm,
        min(ts)             AS exposed_at,
        uniqExact(variant)  AS n_variants
    FROM exposures
    WHERE experiment = {experiment:String}
      AND ts >= {start:DateTime} AND ts < {enroll_end:DateTime}
    GROUP BY player_id
    HAVING exposed_at <= {as_of:DateTime} - INTERVAL {window:UInt32} DAY
),
bet_agg AS (
    SELECT
        f.player_id AS player_id,
        countIf(b.ts >= f.exposed_at AND b.ts < f.exposed_at + INTERVAL {window:UInt32} DAY)  AS bets,
        sumIf(b.stake_cents, b.ts >= f.exposed_at AND b.ts < f.exposed_at + INTERVAL {window:UInt32} DAY) AS stake_c,
        sumIf(b.payout_cents, b.ts >= f.exposed_at AND b.ts < f.exposed_at + INTERVAL {window:UInt32} DAY) AS payout_c,
        countIf(b.ts < f.exposed_at AND b.ts >= f.exposed_at - INTERVAL {pre:UInt32} DAY)     AS pre_bets,
        sumIf(b.stake_cents, b.ts < f.exposed_at AND b.ts >= f.exposed_at - INTERVAL {pre:UInt32} DAY) AS pre_stake_c,
        sumIf(b.payout_cents, b.ts < f.exposed_at AND b.ts >= f.exposed_at - INTERVAL {pre:UInt32} DAY) AS pre_payout_c
    FROM first_exposure f
    INNER JOIN bets b ON b.player_id = f.player_id
    GROUP BY f.player_id
),
dep_agg AS (
    SELECT
        f.player_id AS player_id,
        countIf(d.ts >= f.exposed_at AND d.ts < f.exposed_at + INTERVAL {window:UInt32} DAY)  AS deposits,
        sumIf(d.amount_cents, d.ts >= f.exposed_at AND d.ts < f.exposed_at + INTERVAL {window:UInt32} DAY) AS deposit_c,
        countIf(d.ts < f.exposed_at AND d.ts >= f.exposed_at - INTERVAL {pre:UInt32} DAY)     AS pre_deposits,
        sumIf(d.amount_cents, d.ts < f.exposed_at AND d.ts >= f.exposed_at - INTERVAL {pre:UInt32} DAY) AS pre_deposit_c
    FROM first_exposure f
    INNER JOIN deposits d ON d.player_id = f.player_id
    GROUP BY f.player_id
)
SELECT
    {experiment:String}                         AS experiment,
    f.player_id                                 AS player_id,
    f.arm                                       AS variant,
    f.exposed_at                                AS exposed_at,
    toUInt8(least(f.n_variants, 255))           AS n_variants,
    p.country, p.segment, p.device,
    ba.bets                                     AS bets,
    ba.stake_c / 100                            AS stake,
    ba.payout_c / 100                           AS payout,
    (ba.stake_c - ba.payout_c) / 100            AS ggr,
    da.deposits                                 AS deposits,
    da.deposit_c / 100                          AS deposit_amount,
    toUInt8(da.deposits > 0)                    AS converted,
    ba.pre_bets                                 AS pre_bets,
    ba.pre_stake_c / 100                        AS pre_stake,
    (ba.pre_stake_c - ba.pre_payout_c) / 100    AS pre_ggr,
    da.pre_deposit_c / 100                      AS pre_deposit_amount,
    toUInt8(da.pre_deposits > 0)                AS pre_converted,
    now()                                       AS built_at
FROM first_exposure f
LEFT JOIN bet_agg ba ON ba.player_id = f.player_id
LEFT JOIN dep_agg da ON da.player_id = f.player_id
LEFT JOIN players p ON p.player_id = f.player_id
SETTINGS join_use_nulls = 0
"""


def build(client: Client, exp: Experiment, as_of: datetime | None = None) -> int:
    """Rebuild the mart of one experiment (idempotent). Returns the number of players."""
    as_of = as_of or exp.ends_at
    client.command(f"ALTER TABLE mart_user_metrics DROP PARTITION '{exp.key}'")
    client.command(
        BUILD_SQL,
        parameters={
            "experiment": exp.key,
            "start": exp.starts_at.replace(tzinfo=UTC),
            "enroll_end": exp.enrollment_ends_at.replace(tzinfo=UTC),
            "as_of": as_of.replace(tzinfo=UTC),
            "window": exp.window_days,
            "pre": exp.pre_days,
        },
    )
    return int(
        client.query(
            "SELECT count() FROM mart_user_metrics WHERE experiment = {e:String}",
            parameters={"e": exp.key},
        ).result_rows[0][0]
    )
