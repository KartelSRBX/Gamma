"""Experiment definitions and the metric catalog, validated as a set.

An experiment is a reviewed YAML file. Loading refuses what would silently corrupt a test:
two experiments of one layer sharing buckets (a player could be in both), a metric nobody
defined, a hypothesis nobody wrote down.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Literal, Self

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

BUCKETS = 10_000
ROOT = Path(__file__).resolve().parents[2]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Variant(_Strict):
    name: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    weight: float = Field(gt=0)


class Guardrail(_Strict):
    metric: str
    # The experiment must not be shipped if this metric is worse than control by more than this
    # share of the control value.
    max_relative_drop: float = Field(gt=0, lt=1)


class Design(_Strict):
    alpha: float = Field(0.05, gt=0, lt=0.5)
    power: float = Field(0.8, gt=0.5, lt=1)
    # Smallest relative change of the primary metric worth detecting.
    mde: float = Field(gt=0, lt=1)


class Metric(_Strict):
    name: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    kind: Literal["binary", "continuous", "ratio"]
    num: str
    den: str | None = None
    pre: str | None = None
    better: Literal["higher", "lower"]
    description: str

    @model_validator(mode="after")
    def _ratio_needs_den(self) -> Self:
        if (self.kind == "ratio") != (self.den is not None):
            raise ValueError(
                f"metric {self.name}: `den` is required for ratio metrics, and only then"
            )
        return self


class Experiment(_Strict):
    key: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    layer: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    owner: str
    hypothesis: str
    start: date
    enrollment_days: int = Field(gt=0, le=90)
    window_days: int = Field(gt=0, le=90)
    pre_days: int = Field(ge=0, le=90)
    buckets: tuple[int, int]
    variants: list[Variant]
    primary: str
    secondary: list[str] = []
    guardrails: list[Guardrail] = []
    design: Design

    @field_validator("hypothesis")
    @classmethod
    def _hypothesis_written(cls, v: str) -> str:
        if len(v.split()) < 8:
            raise ValueError(
                "write the hypothesis as a sentence: what changes, for whom, which metric"
            )
        return v.strip()

    @field_validator("buckets")
    @classmethod
    def _bucket_range(cls, v: tuple[int, int]) -> tuple[int, int]:
        lo, hi = v
        if not 0 <= lo <= hi < BUCKETS:
            raise ValueError(f"buckets must satisfy 0 <= lo <= hi < {BUCKETS}, got {v}")
        return v

    @model_validator(mode="after")
    def _variants(self) -> Self:
        names = [v.name for v in self.variants]
        if len(names) < 2 or len(set(names)) != len(names):
            raise ValueError("need at least two variants with distinct names")
        if names[0] != "control":
            raise ValueError("the first variant must be `control`")
        return self

    @property
    def traffic(self) -> float:
        """Share of the layer's players that enter the experiment."""
        return (self.buckets[1] - self.buckets[0] + 1) / BUCKETS

    @property
    def starts_at(self) -> datetime:
        return datetime.combine(self.start, time())

    @property
    def enrollment_ends_at(self) -> datetime:
        return self.starts_at + timedelta(days=self.enrollment_days)

    @property
    def ends_at(self) -> datetime:
        """When the last enrolled player has a complete window: the earliest full analysis date."""
        return self.enrollment_ends_at + timedelta(days=self.window_days)

    @property
    def metric_names(self) -> list[str]:
        return [self.primary, *self.secondary, *(g.metric for g in self.guardrails)]


class Catalog(_Strict):
    metrics: dict[str, Metric]
    experiments: dict[str, Experiment]

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        for exp in self.experiments.values():
            for m in exp.metric_names:
                if m not in self.metrics:
                    raise ValueError(f"experiment {exp.key} uses unknown metric `{m}`")
            if exp.primary in exp.secondary:
                raise ValueError(
                    f"experiment {exp.key}: primary metric is also listed as secondary"
                )
        by_layer: dict[str, list[Experiment]] = {}
        for exp in self.experiments.values():
            by_layer.setdefault(exp.layer, []).append(exp)
        for layer, exps in by_layer.items():
            for i, a in enumerate(exps):
                for b in exps[i + 1 :]:
                    overlap_in_time = a.starts_at < b.ends_at and b.starts_at < a.ends_at
                    if (
                        overlap_in_time
                        and a.buckets[0] <= b.buckets[1]
                        and b.buckets[0] <= a.buckets[1]
                    ):
                        raise ValueError(
                            f"layer `{layer}`: {a.key} {list(a.buckets)} and {b.key} "
                            f"{list(b.buckets)} share buckets while both run, "
                            "a player could be in both"
                        )
        return self


def load_catalog(root: Path = ROOT) -> Catalog:
    raw = yaml.safe_load((root / "catalog" / "metrics.yaml").read_text())
    metrics = {m["name"]: Metric(**m) for m in raw["metrics"]}
    experiments: dict[str, Experiment] = {}
    for path in sorted((root / "experiments").glob("*.yaml")):
        exp = Experiment(**yaml.safe_load(path.read_text()))
        if exp.key != path.stem:
            raise ValueError(f"{path.name}: key `{exp.key}` must match the file name")
        experiments[exp.key] = exp
    return Catalog(metrics=metrics, experiments=experiments)
