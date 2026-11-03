"""Ordered SQL migrations with checksums, so an applied migration cannot be edited quietly."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

from clickhouse_connect.driver.client import Client

from .config import ROOT

SCHEMA_DIR = ROOT / "schema"

TRACKING = """
CREATE TABLE IF NOT EXISTS schema_migrations
(
    name       String,
    checksum   String,
    applied_at DateTime DEFAULT now()
)
ENGINE = MergeTree
ORDER BY name
"""


def split_statements(sql: str) -> list[str]:
    """Statements separated by `;`. Comments are removed first so a `;` in one cannot split."""
    no_comments = re.sub(r"--[^\n]*", "", sql)
    return [s.strip() for s in no_comments.split(";") if s.strip()]


def migrate(client: Client, schema_dir: Path = SCHEMA_DIR) -> list[str]:
    """Apply what is not applied yet. Returns the names applied, empty when up to date."""
    client.command(TRACKING)
    applied = dict(client.query("SELECT name, checksum FROM schema_migrations").result_rows)
    done: list[str] = []
    for path in sorted(schema_dir.glob("[0-9][0-9][0-9]_*.sql")):
        text = path.read_text()
        checksum = hashlib.sha256(text.encode()).hexdigest()
        if path.name in applied:
            if applied[path.name] != checksum:
                raise RuntimeError(
                    f"{path.name} was changed after it was applied; write a new migration instead"
                )
            continue
        for statement in split_statements(text):
            client.command(statement)
        client.insert(
            "schema_migrations", [[path.name, checksum]], column_names=["name", "checksum"]
        )
        done.append(path.name)
    return done
