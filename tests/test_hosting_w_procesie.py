"""Szwy pod hostowanie narzędzi bpp-mcp w procesie hosta (BPP wystawiające
własne ``/mcp``): wstrzykiwany transport httpx, jawny tryb uwierzytelniania,
podmienialny słownik cache oraz publiczna rejestracja narzędzi.

Testy pilnują też, że domyślne wartości nowych parametrów odtwarzają
zachowanie sprzed ich wprowadzenia — pakiet jest na PyPI i ma użytkowników.
"""

from __future__ import annotations

import httpx
import pytest
import respx
from mcp.server.fastmcp import FastMCP

from bpp_mcp import auth
from bpp_mcp.client import BppClient, BppError, TrybAuth
from bpp_mcp.config import Config
from bpp_mcp.server import _register, register_tools

BASE = "https://bpp.example.test"
PING = f"{BASE}/api/v1/uczelnia/1/"
SLOWNIK = f"{BASE}/api/v1/jezyk/"


def _cfg(basic: str | None = None, transport: str = "stdio") -> Config:
    return Config(base_url=BASE, basic_auth=basic, transport=transport)


@pytest.fixture(autouse=True)
def _czysty_bearer():
    auth.set_current_bearer(None)
    yield
    auth.set_current_bearer(None)


# --- A. wstrzykiwany transport httpx ----------------------------------------


async def test_wstrzykniety_transport_obsluguje_zadanie():
    """``transport=`` faktycznie zastępuje warstwę sieciową — żądanie kończy
    się w handlerze MockTransport, nie w gnieździe."""
    przechwycone: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        przechwycone.append(request)
        return httpx.Response(200, json={"skad": "z-procesu"})

    async with BppClient(_cfg(), transport=httpx.MockTransport(handler)) as c:
        dane = await c.get_json("uczelnia/1/")

    assert dane == {"skad": "z-procesu"}
    assert [str(r.url) for r in przechwycone] == [PING]


@respx.mock
async def test_bez_transportu_leci_domyslna_sciezka():
    """Kontrola negatywna do poprzedniego: domyślne ``transport=None`` zostawia
    zwykły transport httpx (respx go przechwytuje)."""
    route = respx.get(PING).mock(return_value=httpx.Response(200, json={"ok": 1}))
    async with BppClient(_cfg()) as c:
        await c.get_json("uczelnia/1/")
    assert route.called


# --- B. trzy tryby polityki uwierzytelniania --------------------------------


def test_tryb_wyprowadzony_z_transportu():
    """Bez jawnego ``tryb_auth`` polityka wynika z ``config.transport`` —
    dokładnie jak przed wprowadzeniem enumeracji."""
    assert BppClient(_cfg()).tryb_auth is TrybAuth.LOKALNY
    assert BppClient(_cfg(transport="http")).tryb_auth is TrybAuth.ZDALNY
    assert (
        BppClient(_cfg(), tryb_auth=TrybAuth.W_PROCESIE).tryb_auth
        is TrybAuth.W_PROCESIE
    )


@respx.mock
async def test_lokalny_bez_bearera_uzywa_basic():
    route = respx.get(PING).mock(return_value=httpx.Response(200, json={"ok": 1}))
    async with BppClient(_cfg(basic="u:p"), tryb_auth=TrybAuth.LOKALNY) as c:
        await c.get_json("uczelnia/1/")
    # Basic base64("u:p") == "dTpw"
    assert route.calls.last.request.headers["Authorization"] == "Basic dTpw"


@respx.mock
async def test_zdalny_bez_bearera_nadal_rzuca():
    """Regresja: tryb zdalny nie wolno, żeby po zmianie zaczął przepuszczać
    żądanie anonimowo albo przez konto serwisowe."""
    respx.get(PING).mock(return_value=httpx.Response(200, json={"ok": 1}))
    async with BppClient(_cfg(basic="u:p"), tryb_auth=TrybAuth.ZDALNY) as c:
        with pytest.raises(BppError):
            await c.get_json("uczelnia/1/")


@respx.mock
async def test_w_procesie_bez_bearera_idzie_anonimowo_mimo_basic():
    """Sedno trybu w-procesie: brak bearera to NIE błąd (jak w zdalnym) i NIE
    powód, by sięgnąć po Basic (jak w lokalnym) — request leci anonimowo.
    Basic omijałby scope tokenu i jego revoke, więc jest tu zakazany."""
    route = respx.get(PING).mock(return_value=httpx.Response(200, json={"ok": 1}))
    async with BppClient(_cfg(basic="u:p"), tryb_auth=TrybAuth.W_PROCESIE) as c:
        await c.get_json("uczelnia/1/")
    assert "Authorization" not in route.calls.last.request.headers


@respx.mock
async def test_w_procesie_z_bearerem_forwarduje_token():
    auth.set_current_bearer("TOKEN-Z-ZADANIA")
    route = respx.get(PING).mock(return_value=httpx.Response(200, json={"ok": 1}))
    async with BppClient(_cfg(basic="u:p"), tryb_auth=TrybAuth.W_PROCESIE) as c:
        await c.get_json("uczelnia/1/")
    assert route.calls.last.request.headers["Authorization"] == "Bearer TOKEN-Z-ZADANIA"


# --- C. szew na cache -------------------------------------------------------


@respx.mock
async def test_szew_cache_kieruje_wpisy_do_slownika_podklasy():
    """Podklasa oddająca własny słownik dostaje do niego wpisy, a per-instancyjny
    ``_cache`` zostaje pusty — tak host trzyma cache per-żądanie."""
    zewnetrzny: dict[str, object] = {}

    class KlientHosta(BppClient):
        def _slownik_cache(self):
            return zewnetrzny

    respx.get(SLOWNIK).mock(return_value=httpx.Response(200, json={"results": []}))
    async with KlientHosta(_cfg()) as c:
        await c.get_json("jezyk/")
        await c.get_json("jezyk/")

    assert list(zewnetrzny) == [SLOWNIK]
    assert c._cache == {}
    # Drugi odczyt obsłużony z podstawionego cache — tylko jedno żądanie.
    assert respx.calls.call_count == 1


@respx.mock
async def test_bazowa_klasa_cachuje_jak_dotad():
    """Kontrola pozytywna: bez podklasy wpisy idą do ``self._cache``."""
    respx.get(SLOWNIK).mock(return_value=httpx.Response(200, json={"results": []}))
    async with BppClient(_cfg()) as c:
        await c.get_json("jezyk/")
        assert c._slownik_cache() is c._cache
        assert list(c._cache) == [SLOWNIK]


# --- D. publiczna rejestracja narzędzi --------------------------------------


async def _zarejestrowane(rejestruj) -> tuple[set[str], set[str]]:
    mcp = FastMCP("test-hosta")
    rejestruj(mcp)
    narzedzia = {n.name for n in await mcp.list_tools()}
    prompty = {p.name for p in await mcp.list_prompts()}
    return narzedzia, prompty


async def test_register_tools_rejestruje_pelny_zestaw():
    narzedzia, prompty = await _zarejestrowane(register_tools)
    assert len(narzedzia) == 11
    assert "zapytanie_rekord" in narzedzia and "djangoql_schema" in narzedzia
    assert prompty == {"zloz_zapytanie_djangoql"}


async def test_alias_register_rejestruje_to_samo():
    """``_register`` zostaje aliasem — pakiet jest na PyPI, a ktoś mógł już
    sięgnąć po prywatną nazwę."""
    assert _register is register_tools
    assert await _zarejestrowane(_register) == await _zarejestrowane(register_tools)


def test_szwy_hostowania_reeksportowane_z_pakietu():
    import bpp_mcp

    assert bpp_mcp.register_tools is register_tools
    assert "register_tools" in bpp_mcp.__all__ and "KontekstApp" in bpp_mcp.__all__
