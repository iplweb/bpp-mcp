"""Wspólne fixtury testów: klient BPP wskazujący na fikcyjny host (respx
przechwytuje ruch httpx — żadnych żywych wywołań).

Od portu na SDK 2.0 sam respx nie wystarcza jako gwarancja offline: SDK poszło
na ``httpx2``, którego respx NIE przechwytuje (sprawdzone — żądanie wychodzi
do sieci). Test idący przez stos SDK mógłby więc po cichu odpytać prawdziwy
serwer, a ``docs/rozwoj.md`` obiecuje, że pakiet testów jest w pełni offline.
Dlatego blokujemy połączenia wychodzące na poziomie gniazd — patrz
:func:`_bez_sieci`."""

from __future__ import annotations

import os
import socket

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


_LOKALNE = {"127.0.0.1", "::1", "localhost", ""}


@pytest.fixture(autouse=True)
def _bez_sieci(monkeypatch):
    """Zablokuj połączenia wychodzące poza localhost w KAŻDYM teście.

    Pętla zwrotna zostaje dozwolona, bo testy logowania OAuth stawiają
    prawdziwy serwer loopback (RFC 8252) i muszą się z nim połączyć.

    Ta blokada jest bezpiecznikiem, nie podstawowym mechanizmem — ruch httpx
    dalej przechwytuje respx. Chodzi o to, żeby żądanie, które respx PRZEOCZY
    (np. wychodzące z httpx2 wewnątrz SDK), padło głośno w teście, zamiast
    cicho odpytać cudzy serwer i przejść.
    """
    prawdziwy_connect = socket.socket.connect

    def _connect(self, address, *args, **kwargs):
        host = address[0] if isinstance(address, tuple) else None
        if host is not None and host not in _LOKALNE:
            raise RuntimeError(
                f"Test próbował połączyć się z siecią: {address!r}. "
                "Pakiet testów ma być offline — zamockuj to żądanie "
                "(respx dla httpx; httpx2 z wnętrza SDK respx NIE łapie)."
            )
        return prawdziwy_connect(self, address, *args, **kwargs)

    monkeypatch.setattr(socket.socket, "connect", _connect)


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
