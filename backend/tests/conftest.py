"""Put the backend package root on sys.path so tests import the modules directly."""

import sys
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from agents import CryonavOrchestrator  # noqa: E402
from fortyguard_service import FortyGuardService  # noqa: E402
from routing_engine import RoutingEngine  # noqa: E402


@pytest.fixture(scope="session")
def service() -> FortyGuardService:
    # No API key: exercises the deterministic simulation path.
    return FortyGuardService(api_key="")


@pytest.fixture(scope="session")
def engine(service: FortyGuardService) -> RoutingEngine:
    return RoutingEngine(service)


@pytest.fixture(scope="session")
def orchestrator(service: FortyGuardService, engine: RoutingEngine) -> CryonavOrchestrator:
    return CryonavOrchestrator(service, engine)


@pytest.fixture(scope="session")
def all_presets(service: FortyGuardService):
    """Every (city, preset, profile) combination the demo can produce."""
    combos = []
    for city_id in service.city_ids():
        for preset in service.city(city_id)["presets"]:
            for profile in ("pedestrian", "delivery_worker", "elderly_vulnerable"):
                combos.append(
                    (
                        city_id,
                        preset["id"],
                        tuple(preset["origin"]["coords"]),
                        tuple(preset["destination"]["coords"]),
                        profile,
                    )
                )
    return combos
