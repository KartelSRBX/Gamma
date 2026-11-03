-- Raw facts. Money is stored as integer cents: no rounding surprises in sums, and cheap to compress.

CREATE TABLE IF NOT EXISTS players
(
    player_id     UInt64,
    registered_at DateTime,
    country       LowCardinality(String),
    segment       LowCardinality(String),
    device        LowCardinality(String)
)
ENGINE = MergeTree
ORDER BY player_id;

-- One row every time the app shows the player an experiment. The same player is logged many
-- times; the analysis is defined on the FIRST exposure, so duplicates are expected, not a bug.
CREATE TABLE IF NOT EXISTS exposures
(
    experiment LowCardinality(String),
    variant    LowCardinality(String),
    player_id  UInt64,
    ts         DateTime
)
ENGINE = MergeTree
PARTITION BY experiment
ORDER BY (experiment, player_id, ts);

CREATE TABLE IF NOT EXISTS bets
(
    player_id    UInt64,
    ts           DateTime,
    stake_cents  UInt32,
    payout_cents UInt32
)
ENGINE = MergeTree
PARTITION BY toYYYYMM(ts)
ORDER BY (player_id, ts);

CREATE TABLE IF NOT EXISTS deposits
(
    player_id    UInt64,
    ts           DateTime,
    amount_cents UInt32
)
ENGINE = MergeTree
PARTITION BY toYYYYMM(ts)
ORDER BY (player_id, ts);
