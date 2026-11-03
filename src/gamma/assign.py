"""Deterministic assignment of players to variants.

No assignment table, no service state: the variant is a pure function of (experiment, player),
so every service that evaluates it gets the same answer, and an analyst can recompute it.

Two hashes, deliberately independent:
  1. layer hash   -> bucket 0..9999. An experiment owns a range of buckets in its layer, so two
                     experiments of one layer can never share a player.
  2. experiment hash -> position in [0, 1), cut by the variant weights. Salting with the
                     experiment key means the same players are not "treatment" in every test, which
                     would correlate the results of different experiments.
"""

from __future__ import annotations

import hashlib

from .config import BUCKETS, Experiment


def _hash64(salt: str, player_id: int) -> int:
    digest = hashlib.blake2b(f"{salt}:{player_id}".encode(), digest_size=8).digest()
    return int.from_bytes(digest, "big")


def bucket(layer: str, player_id: int) -> int:
    return _hash64(f"layer:{layer}", player_id) % BUCKETS


def position(experiment_key: str, player_id: int) -> float:
    """Uniform in [0, 1) from the top 53 bits, the precision of a float."""
    return (_hash64(f"experiment:{experiment_key}", player_id) >> 11) / (1 << 53)


def assign(exp: Experiment, player_id: int) -> str | None:
    """The variant for this player, or None when the player is not in the experiment's traffic."""
    lo, hi = exp.buckets
    if not lo <= bucket(exp.layer, player_id) <= hi:
        return None
    u = position(exp.key, player_id) * sum(v.weight for v in exp.variants)
    edge = 0.0
    for v in exp.variants:
        edge += v.weight
        if u < edge:
            return v.name
    return exp.variants[-1].name  # float rounding at the very top edge
