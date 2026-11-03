"""Persist an analysis, its verdict and the segment breakdown."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from clickhouse_connect.driver.client import Client

from .analyze import Analysis
from .segments import SegmentResult
from .verdict import Verdict

RESULT_COLUMNS = [
    "run_id",
    "experiment",
    "run_at",
    "role",
    "metric",
    "dimension",
    "value",
    "method",
    "n_control",
    "n_treatment",
    "mean_control",
    "mean_treatment",
    "diff",
    "rel_diff",
    "rel_ci_low",
    "rel_ci_high",
    "p",
    "p_adjusted",
    "variance_reduction",
    "guardrail",
]


def save(client: Client, a: Analysis, verdict: Verdict, segments: list[SegmentResult]) -> uuid.UUID:
    run_id, now = uuid.uuid4(), datetime.now(UTC)
    key = a.experiment.key
    client.insert(
        "experiment_runs",
        [
            [
                run_id,
                key,
                now,
                a.as_of.replace(tzinfo=UTC),
                int(a.at_horizon),
                verdict.decision,
                verdict.headline,
                a.srm.p,
                int(a.valid),
                a.excluded_multi_variant,
                a.warnings,
            ]
        ],
        column_names=[
            "run_id",
            "experiment",
            "run_at",
            "as_of",
            "at_horizon",
            "decision",
            "headline",
            "srm_p",
            "valid",
            "excluded_multi_variant",
            "warnings",
        ],
    )
    rows = []
    for r in a.results:
        e = r.estimate
        rows.append(
            [
                run_id,
                key,
                now,
                r.role,
                r.metric.name,
                "all",
                "all",
                e.method,
                e.n_control,
                e.n_treatment,
                e.mean_control,
                e.mean_treatment,
                e.diff,
                e.rel_diff,
                e.rel_ci[0],
                e.rel_ci[1],
                e.p,
                r.p_adjusted,
                e.variance_reduction,
                r.guardrail or "",
            ]
        )
    primary = next(r for r in a.results if r.role == "primary")
    for s in segments:
        e = s.estimate
        rows.append(
            [
                run_id,
                key,
                now,
                "segment",
                primary.metric.name,
                s.dimension,
                s.value,
                e.method,
                e.n_control,
                e.n_treatment,
                e.mean_control,
                e.mean_treatment,
                e.diff,
                e.rel_diff,
                e.rel_ci[0],
                e.rel_ci[1],
                e.p,
                s.p_adjusted,
                e.variance_reduction,
                "",
            ]
        )
    client.insert("experiment_results", rows, column_names=RESULT_COLUMNS)
    return run_id
