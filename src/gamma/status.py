"""A quick look at what is in the database, as numbers an analyst checks first."""

from __future__ import annotations

from clickhouse_connect.driver.client import Client


def counts(client: Client) -> dict[str, int]:
    return {
        t: int(client.query(f"SELECT count() FROM {t}").result_rows[0][0])
        for t in ("players", "exposures", "bets", "deposits", "mart_user_metrics")
    }


def arms(client: Client, experiment: str) -> list[tuple[str, int, float, float, int]]:
    """variant, players, conversion, deposit per player, players that saw several variants."""
    return [
        (v, int(n), float(c), float(d), int(x))
        for v, n, c, d, x in client.query(
            """
            SELECT variant, count(), avg(converted), avg(deposit_amount), countIf(n_variants > 1)
            FROM mart_user_metrics WHERE experiment = {e:String}
            GROUP BY variant ORDER BY variant != 'control', variant
            """,
            parameters={"e": experiment},
        ).result_rows
    ]
