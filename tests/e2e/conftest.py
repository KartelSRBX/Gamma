"""One simulated world for all end-to-end tests: 40k players, fixed seed, so results are exact."""

from __future__ import annotations

import pytest

from gamma import ch, marts
from gamma.config import load_catalog
from gamma.migrate import migrate
from gamma.simulate import load, load_scenario, simulate

PLAYERS = 40_000


@pytest.fixture(scope="session")
def client():
    return ch.connect()


@pytest.fixture(scope="session")
def catalog():
    return load_catalog()


@pytest.fixture(scope="session", autouse=True)
def world(client, catalog):
    migrate(client)
    scenario = load_scenario()
    scenario.players = PLAYERS
    load(client, simulate(scenario, catalog))
    for exp in catalog.experiments.values():
        marts.build(client, exp)
    return scenario
