-- What the analysis concluded, kept for every run, so dashboards and BI tools read conclusions
-- instead of recomputing them, and so a decision can be traced to the numbers it was made on.
CREATE TABLE IF NOT EXISTS experiment_runs
(
    run_id        UUID,
    experiment    LowCardinality(String),
    run_at        DateTime64(3) DEFAULT now64(3),
    as_of         DateTime,
    at_horizon    UInt8,
    decision      LowCardinality(String),
    headline      String,
    srm_p         Float64,
    valid         UInt8,
    excluded_multi_variant UInt32,
    warnings      Array(String)
)
ENGINE = MergeTree
ORDER BY (experiment, run_at);

-- One row per metric (dimension = 'all') and per segment of the primary metric.
CREATE TABLE IF NOT EXISTS experiment_results
(
    run_id             UUID,
    experiment         LowCardinality(String),
    run_at             DateTime64(3),
    role               LowCardinality(String),
    metric             LowCardinality(String),
    dimension          LowCardinality(String),
    value              LowCardinality(String),
    method             LowCardinality(String),
    n_control          UInt32,
    n_treatment        UInt32,
    mean_control       Float64,
    mean_treatment     Float64,
    diff               Float64,
    rel_diff           Float64,
    rel_ci_low         Float64,
    rel_ci_high        Float64,
    p                  Float64,
    p_adjusted         Nullable(Float64),
    variance_reduction Nullable(Float64),
    guardrail          LowCardinality(String)
)
ENGINE = MergeTree
ORDER BY (experiment, run_at, role, metric, dimension, value);

-- The latest run of each experiment: the views a dashboard or Tableau connects to.
CREATE VIEW IF NOT EXISTS v_latest_run AS
SELECT * FROM experiment_runs
WHERE run_id IN (SELECT argMax(run_id, run_at) FROM experiment_runs GROUP BY experiment);

CREATE VIEW IF NOT EXISTS v_latest_results AS
SELECT r.*, runs.decision AS decision, runs.as_of AS as_of, runs.valid AS valid
FROM experiment_results AS r
INNER JOIN v_latest_run AS runs ON r.run_id = runs.run_id;
