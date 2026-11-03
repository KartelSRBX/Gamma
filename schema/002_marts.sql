-- One row per player per experiment: what the player did in the pre-period and in the
-- post-exposure window. Statistics read this table and nothing else, so every method sees the
-- same unit of analysis (the randomisation unit: the player).
CREATE TABLE IF NOT EXISTS mart_user_metrics
(
    experiment       LowCardinality(String),
    player_id        UInt64,
    variant          LowCardinality(String),
    exposed_at       DateTime,
    -- more than one means the player saw several variants: a randomisation bug to surface
    n_variants       UInt8,
    country          LowCardinality(String),
    segment          LowCardinality(String),
    device           LowCardinality(String),

    bets             UInt32,
    stake            Float64,
    payout           Float64,
    ggr              Float64,
    deposits         UInt32,
    deposit_amount   Float64,
    converted        UInt8,

    pre_bets           UInt32,
    pre_stake          Float64,
    pre_ggr            Float64,
    pre_deposit_amount Float64,
    pre_converted      UInt8,

    built_at         DateTime DEFAULT now()
)
ENGINE = MergeTree
PARTITION BY experiment
ORDER BY (experiment, player_id);
