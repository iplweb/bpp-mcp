"""Wspólne fixtury testów: klient BPP wskazujący na fikcyjny host (respx
przechwytuje ruch httpx — żadnych żywych wywołań)."""

from __future__ import annotations

import os

BASE_URL = "https://bpp.test"

# BPP_BASE_URL jest wymagany i nie ma wartości domyślnej, a ``bpp_mcp.server``
# buduje serwer już przy imporcie — więc host trzeba ustawić ZANIM pytest
# zaimportuje moduły testowe (fixtury są na to za późno). Ustawiamy na sztywno,
# nie ``setdefault``, żeby zmienna z powłoki dewelopera nie zmieniała wyników.
os.environ["BPP_BASE_URL"] = BASE_URL

import pytest  # noqa: E402

from bpp_mcp.client import BppClient  # noqa: E402
from bpp_mcp.config import Config  # noqa: E402

API_ROOT = f"{BASE_URL}/api/v1"


@pytest.fixture(autouse=True)
def _izolacja_config(tmp_path, monkeypatch):
    """Izoluj token_store od realnego ~/.config w KAŻDYM teście — po wpięciu
    OAuth stdio lifespan serwera tworzy TokenProvider → token_store.load(),
    więc bez izolacji test czytałby prawdziwy token dewelopera."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))


@pytest.fixture
def config() -> Config:
    return Config(base_url=BASE_URL)


@pytest.fixture
async def client(config: Config):
    # backoff_base=0.0 → retry bez realnego sleepu (szybkie testy błędów sieci).
    c = BppClient(config, backoff_base=0.0)
    try:
        yield c
    finally:
        await c.aclose()
