"""Wspólne fixtury testów: klient BPP wskazujący na fikcyjny host (respx
przechwytuje ruch httpx — żadnych żywych wywołań)."""

from __future__ import annotations

import pytest

from bpp_mcp.client import BppClient
from bpp_mcp.config import Config

BASE_URL = "https://bpp.test"
API_ROOT = f"{BASE_URL}/api/v1"


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
