"""Connection to ClickHouse."""

from __future__ import annotations

import logging
import os

import clickhouse_connect
from clickhouse_connect.driver.client import Client

logging.getLogger("clickhouse_connect").setLevel(logging.CRITICAL)

HOST = os.environ.get("CH_HOST", "localhost")
PORT = int(os.environ.get("CH_PORT", "8123"))
USER = os.environ.get("CH_USER", "gamma")
PASSWORD = os.environ.get("CH_PASSWORD", "gamma")
DATABASE = os.environ.get("CH_DATABASE", "gamma")


def connect(**settings: object) -> Client:
    return clickhouse_connect.get_client(
        host=HOST,
        port=PORT,
        username=USER,
        password=PASSWORD,
        database=DATABASE,
        send_receive_timeout=300,
        settings=settings,
    )
