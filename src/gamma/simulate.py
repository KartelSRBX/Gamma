"""A synthetic casino whose truth is known, so the analysis can be checked against it.

Players have a latent activity level that drives how much they bet and deposit, in the pre-period
and after exposure alike. That is what makes pre-period behaviour predict post-period behaviour
(and CUPED worth having), and what makes money metrics heavy-tailed, as they are in production.

Assignment goes through the same `assign()` the platform uses. The true effect of a variant is a
multiplier on the player's rates from their first exposure on. Known data-quality faults can be
injected on purpose.

Simplifications, on purpose: only players who see at least one experiment get events (the rest
cannot affect any result), and one experiment per scenario carries a real effect, so each player
has at most one change point and events can be drawn exactly.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Self

import numpy as np
import yaml
from clickhouse_connect.driver.client import Client
from pydantic import BaseModel, ConfigDict, Field, model_validator

from .assign import assign
from .config import ROOT, Catalog

DAY = 86_400
EPOCH_OFFSET = np.datetime64("1970-01-01T00:00:00", "s")

# share of players, bets/day, median stake, deposits/day, median deposit (EUR)
SEGMENTS = {
    "casual": (0.70, 0.25, 1.5, 0.03, 20.0),
    "regular": (0.25, 1.2, 4.0, 0.07, 50.0),
    "vip": (0.05, 6.0, 15.0, 0.20, 300.0),
}
DEVICES = {"ios": 0.35, "android": 0.45, "web": 0.20}
COUNTRIES = {"RS": 0.40, "HR": 0.15, "BA": 0.15, "ME": 0.07, "MK": 0.07, "SI": 0.06, "AL": 0.10}
WIN_PROBABILITY = 0.30
WIN_MULTIPLIER = 3.2  # 0.30 * 3.2 = 96% return to player, the usual slot RTP
VISIT_RATE_PER_DAY = 0.5  # first visit after the start of a test, times the player's activity


class Effect(BaseModel):
    model_config = ConfigDict(extra="forbid")
    deposit_rate: float = Field(1.0, gt=0)
    bet_rate: float = Field(1.0, gt=0)
    stake: float = Field(1.0, gt=0)

    @property
    def is_identity(self) -> bool:
        return self.deposit_rate == self.bet_rate == self.stake == 1.0


class Fault(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["drop_exposure", "crossover"]
    experiment: str
    variant: str | None = None
    device: str | None = None
    rate: float = Field(gt=0, lt=1)


class Scenario(BaseModel):
    model_config = ConfigDict(extra="forbid")
    seed: int
    players: int = Field(gt=0)
    truth: dict[str, dict[str, Effect]]
    faults: list[Fault] = []

    @model_validator(mode="after")
    def _one_real_effect(self) -> Self:
        real = [k for k, vs in self.truth.items() if any(not e.is_identity for e in vs.values())]
        if len(real) > 1:
            raise ValueError(f"only one experiment may carry a real effect, got {real}")
        return self


def load_scenario(path: Path | None = None) -> Scenario:
    path = path or ROOT / "simulation" / "scenario.yaml"
    return Scenario(**yaml.safe_load(path.read_text()))


@dataclass
class Dataset:
    """Column-oriented tables, timestamps as epoch seconds."""

    players: dict[str, np.ndarray]
    exposures: dict[str, np.ndarray]
    bets: dict[str, np.ndarray]
    deposits: dict[str, np.ndarray]

    @property
    def sizes(self) -> dict[str, int]:
        return {
            "players": len(self.players["player_id"]),
            "exposures": len(self.exposures["player_id"]),
            "bets": len(self.bets["player_id"]),
            "deposits": len(self.deposits["player_id"]),
        }


def _epoch(d) -> int:
    return int((np.datetime64(d, "s") - EPOCH_OFFSET) / np.timedelta64(1, "s"))


def _poisson_events(
    rng: np.random.Generator, rate: np.ndarray, t_a: np.ndarray, t_b: np.ndarray
) -> tuple[np.ndarray, np.ndarray]:
    """Events of a Poisson process with a per-player rate (per day) over [t_a, t_b)."""
    span = np.maximum(t_b - t_a, 0)
    counts = rng.poisson(rate * span / DAY)
    idx = np.repeat(np.arange(len(rate)), counts)
    ts = t_a[idx] + (rng.random(len(idx)) * span[idx]).astype(np.int64)
    return idx, ts


def simulate(scenario: Scenario, catalog: Catalog) -> Dataset:
    rng = np.random.default_rng(scenario.seed)
    n = scenario.players
    exps = [catalog.experiments[k] for k in scenario.truth]
    for k in scenario.truth:
        if k not in catalog.experiments:
            raise ValueError(f"scenario names unknown experiment `{k}`")
    for f in scenario.faults:
        if f.experiment not in scenario.truth:
            raise ValueError(f"fault names experiment `{f.experiment}` that is not in `truth`")

    t0 = min(_epoch(e.start) - e.pre_days * DAY for e in exps)
    t_end = max(_epoch(e.ends_at) for e in exps)

    # --- players -------------------------------------------------------------------------------
    seg_names = list(SEGMENTS)
    seg = rng.choice(len(seg_names), size=n, p=[SEGMENTS[s][0] for s in seg_names])
    seg_params = np.array([SEGMENTS[s][1:] for s in seg_names])  # bets, stake, dep, dep_amount
    device = rng.choice(list(DEVICES), size=n, p=list(DEVICES.values()))
    country = rng.choice(list(COUNTRIES), size=n, p=list(COUNTRIES.values()))
    activity = rng.lognormal(0.0, 0.6, n)
    bet_rate = seg_params[seg, 0] * activity
    stake_median = seg_params[seg, 1] * rng.lognormal(0.0, 0.4, n)
    dep_rate = seg_params[seg, 2] * activity**0.7 * rng.lognormal(0.0, 0.5, n)
    dep_median = seg_params[seg, 3] * rng.lognormal(0.0, 0.3, n)
    player_id = 10_000_000 + np.arange(n, dtype=np.uint64)
    registered_at = t0 - rng.integers(1, 400 * DAY, n)

    # --- exposure: who sees which variant, and when --------------------------------------------
    exposed_any = np.zeros(n, dtype=bool)
    change_at = np.full(n, t_end, dtype=np.int64)
    mult = np.ones((n, 3))  # deposit_rate, bet_rate, stake
    log_exp, log_var, log_pid, log_ts = [], [], [], []
    for exp in exps:
        variants = {v.name: i for i, v in enumerate(exp.variants)}
        names = np.array([v.name for v in exp.variants])
        arm = np.array([assign(exp, int(p)) or "" for p in player_id])
        in_traffic = arm != ""
        delay = rng.exponential(1.0 / (VISIT_RATE_PER_DAY * activity)) * DAY
        first = _epoch(exp.start) + delay.astype(np.int64)
        seen = in_traffic & (first < _epoch(exp.enrollment_ends_at))
        exposed_any |= seen

        effects = scenario.truth[exp.key]
        for name, eff in effects.items():
            if name not in variants:
                raise ValueError(f"scenario: `{name}` is not a variant of {exp.key}")
            if eff.is_identity:
                continue
            hit = seen & (arm == name)
            change_at[hit] = first[hit]
            mult[hit] = [eff.deposit_rate, eff.bet_rate, eff.stake]

        # What the app logs: the first exposure plus repeats on later visits.
        logged = seen.copy()
        for f in scenario.faults:
            if f.kind == "drop_exposure" and f.experiment == exp.key:
                hit = seen.copy()
                if f.variant:
                    hit &= arm == f.variant
                if f.device:
                    hit &= device == f.device
                logged &= ~(hit & (rng.random(n) < f.rate))
        idx = np.flatnonzero(logged)
        repeats = rng.poisson(1.5, len(idx))
        ridx = np.repeat(idx, repeats)
        rts = first[ridx] + (rng.random(len(ridx)) * (t_end - first[ridx])).astype(np.int64)
        for p_idx, ts in ((idx, first[idx]), (ridx, rts)):
            log_exp.append(np.full(len(p_idx), exp.key))
            log_var.append(arm[p_idx])
            log_pid.append(player_id[p_idx])
            log_ts.append(ts)
        for f in scenario.faults:
            if f.kind == "crossover" and f.experiment == exp.key:
                flip = np.flatnonzero(logged & (rng.random(n) < f.rate))
                other = names[(np.searchsorted(names, arm[flip]) + 1) % len(names)]
                other = np.where(other == arm[flip], names[0], other)
                late = first[flip] + (rng.random(len(flip)) * 7 * DAY).astype(np.int64)
                log_exp.append(np.full(len(flip), exp.key))
                log_var.append(other)
                log_pid.append(player_id[flip])
                log_ts.append(np.minimum(late, t_end - 1))

    # --- behaviour: events of the players who saw an experiment --------------------------------
    keep = np.flatnonzero(exposed_any)
    m = len(keep)
    t_a = np.full(m, t0, dtype=np.int64)
    t_c = change_at[keep]
    t_b = np.full(m, t_end, dtype=np.int64)

    def draw(rate: np.ndarray, col: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        i1, ts1 = _poisson_events(rng, rate[keep], t_a, t_c)
        i2, ts2 = _poisson_events(rng, rate[keep] * mult[keep, col], t_c, t_b)
        return (
            np.concatenate([i1, i2]),
            np.concatenate([ts1, ts2]),
            np.concatenate([np.zeros(len(i1), bool), np.ones(len(i2), bool)]),
        )

    bi, bts, after = draw(bet_rate, 1)
    stake = (
        stake_median[keep][bi]
        * np.where(after, mult[keep][bi, 2], 1.0)
        * rng.lognormal(0.0, 0.6, len(bi))
    )
    stake_cents = np.clip(np.rint(stake * 100), 10, 5_000_000).astype(np.uint32)
    won = rng.random(len(bi)) < WIN_PROBABILITY
    payout_cents = np.where(
        won,
        np.rint(stake_cents * WIN_MULTIPLIER * rng.lognormal(-0.32, 0.8, len(bi))),
        0,
    ).astype(np.uint32)

    di, dts, _ = draw(dep_rate, 0)
    amount_cents = np.clip(
        np.rint(dep_median[keep][di] * rng.lognormal(0.0, 0.7, len(di)) * 100), 500, 5_000_000
    ).astype(np.uint32)

    return Dataset(
        players={
            "player_id": player_id,
            "registered_at": registered_at,
            "country": country,
            "segment": np.array(seg_names)[seg],
            "device": device,
        },
        exposures={
            "experiment": np.concatenate(log_exp),
            "variant": np.concatenate(log_var),
            "player_id": np.concatenate(log_pid),
            "ts": np.concatenate(log_ts),
        },
        bets={
            "player_id": player_id[keep][bi],
            "ts": bts,
            "stake_cents": stake_cents,
            "payout_cents": payout_cents,
        },
        deposits={"player_id": player_id[keep][di], "ts": dts, "amount_cents": amount_cents},
    )


CHUNK = 500_000
TABLES = ["players", "exposures", "bets", "deposits"]


def load(client: Client, data: Dataset) -> dict[str, int]:
    """Replace the raw tables with the dataset (and drop marts built on the old one)."""
    from datetime import UTC, datetime

    for table in [*TABLES, "mart_user_metrics"]:
        client.command(f"TRUNCATE TABLE {table}")
    for table in TABLES:
        cols: dict[str, np.ndarray] = getattr(data, table)
        names = list(cols)
        total = len(cols[names[0]])
        for lo in range(0, total, CHUNK):
            block = []
            for name in names:
                part = cols[name][lo : lo + CHUNK]
                if name in ("ts", "registered_at"):
                    block.append([datetime.fromtimestamp(int(t), UTC) for t in part])
                else:
                    block.append(part.tolist())
            client.insert(table, block, column_names=names, column_oriented=True)
    return data.sizes
