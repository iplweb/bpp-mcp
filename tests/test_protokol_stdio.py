"""Testy na poziomie PROTOKOŁU: prawdziwy klient MCP rozmawia z naszym
serwerem po stdio, w podprocesie.

Do portu na SDK 2.0 cały pakiet testów dotykał wyłącznie naszego kodu i
powierzchni ASGI — ani jeden test nie robił handshake'u. Tymczasem ryzyko
zmiany SDK jest w większości protokolarne: negocjacja wersji, kształt
``serverInfo``, serializacja listy narzędzi. Te testy zamykają tę lukę.

Sieci nie ruszają: ``initialize``, ``tools/list`` i ``prompts/list`` obsługuje
sam serwer, bez odpytywania BPP. Dzięki temu chodzą w zwykłym CI, a nie tylko
pod markerem „live"."""

from __future__ import annotations

import os
import sys
from contextlib import asynccontextmanager

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from bpp_mcp import __version__

NARZEDZIA = {
    "szukaj_publikacji",
    "szukaj_autora",
    "publikacje_autora",
    "publikacje_jednostki",
    "pobierz_rekord",
    "lista_publikacji",
    "slownik",
    "zapytanie_rekord",
    "zapytanie_autor",
    "zapytanie_autorzy",
    "djangoql_schema",
}


def _parametry() -> StdioServerParameters:
    # Serwer musi dostać BPP_BASE_URL, bo bez niego nie da się go zbudować.
    # Fikcyjny host wystarczy — żadne z wołanych tu żądań nie wychodzi do BPP.
    return StdioServerParameters(
        command=sys.executable,
        args=["-m", "bpp_mcp.server"],
        env={**os.environ, "BPP_BASE_URL": "https://bpp.test"},
    )


@asynccontextmanager
async def _sesja():
    """Klient MCP podpięty do serwera w podprocesie.

    Świadomie NIE jest fixturem pytest: fixture-generator otwierałby te
    konteksty w innym zadaniu asyncio niż je zamyka, a anyio odrzuca to
    komunikatem „Attempted to exit cancel scope in a different task".
    """
    async with stdio_client(_parametry()) as (read, write):
        async with ClientSession(read, write) as session:
            wynik = await session.initialize()
            yield session, wynik


async def test_handshake_podaje_nasza_wersje():
    """``server_info.version`` musi nieść wersję bpp-mcp.

    SDK 2.0 domyśla tu pustego stringa (1.x podstawiało wersję SDK, co i tak
    wprowadzało w błąd — klient widział wersję biblioteki, nie naszą). Bez
    jawnego ``version=`` w ``build_mcp`` klient dostawałby ``""``."""
    async with _sesja() as (_, wynik):
        assert wynik.server_info.name == "bpp-mcp"
        assert wynik.server_info.version == __version__


async def test_lista_narzedzi_po_protokole():
    async with _sesja() as (session, _):
        tools = await session.list_tools()
        assert {t.name for t in tools.tools} == NARZEDZIA


async def test_lista_promptow_po_protokole():
    async with _sesja() as (session, _):
        prompty = await session.list_prompts()
        prompt = next(p for p in prompty.prompts if p.name == "zloz_zapytanie_djangoql")
        assert [a.name for a in (prompt.arguments or [])] == ["opis"]
