"""One simulated world for all end-to-end tests: the scenario's 200k players, fixed seed, so
results are exact. Smaller worlds would leave a 3% lift below what the tests can see."""

from __future__ import annotations

import pytest

from gamma import ch, marts
from gamma.config import load_catalog
from gamma.migrate import migrate
from gamma.simulate import load, load_scenario, simulate


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
    load(client, simulate(scenario, catalog))
    for exp in catalog.experiments.values():
        marts.build(client, exp)
    return scenario
