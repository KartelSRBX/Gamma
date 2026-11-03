"""Does the effect differ between kinds of players? Exploratory, and labelled so.

Splitting an experiment by segment, device and country multiplies the number of tests. Holm
adjusts the segments of one dimension together, and the report says that a segment is a lead for
the next experiment, never a reason to ship to that segment alone.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from clickhouse_connect.driver.client import Client

from . import analyze as analysis
from .config import Experiment, Metric
from .stats import estimators, multiple

DIMENSIONS = ("segment", "device", "country")
MIN_PER_ARM = 500


@dataclass
class SegmentResult:
    dimension: str
    value: str
    estimate: estimators.Estimate
    p_adjusted: float


def by_dimension(
    client: Client, exp: Experiment, metric: Metric, dimensions: tuple[str, ...] = DIMENSIONS
) -> list[SegmentResult]:
    cols = [c for c in (metric.num, metric.den, metric.pre) if c]
    res = client.query(
        f"SELECT variant, {', '.join(dimensions)}, {', '.join(cols)} FROM mart_user_metrics "
        "WHERE experiment = {e:String} AND n_variants = 1 ORDER BY player_id",
        parameters={"e": exp.key},
    )
    rc = res.result_columns
    variant = np.array(rc[0])
    dims = {d: np.array(rc[1 + i]) for i, d in enumerate(dimensions)}
    data = {c: np.asarray(rc[1 + len(dimensions) + i], dtype=float) for i, c in enumerate(cols)}
    treatment = next(v.name for v in exp.variants if v.name != "control")
    out: list[SegmentResult] = []
    for dim, labels in dims.items():
        rows: list[tuple[str, estimators.Estimate]] = []
        for value in sorted(np.unique(labels)):
            m_c = (labels == value) & (variant == "control")
            m_t = (labels == value) & (variant == treatment)
            if min(m_c.sum(), m_t.sum()) < MIN_PER_ARM:
                continue
            c = {k: v[m_c] for k, v in data.items()}
            t = {k: v[m_t] for k, v in data.items()}
            raw, adjusted = analysis.estimate_metric(metric, c, t, exp.design.alpha)
            rows.append((str(value), adjusted or raw))
        adj = multiple.holm([e.p for _, e in rows]) if rows else []
        out += [SegmentResult(dim, value, e, p) for (value, e), p in zip(rows, adj, strict=True)]
    return out
