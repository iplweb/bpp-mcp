from __future__ import annotations

import asyncio
import time

import pytest

from bpp_mcp import login_state, token_store
from bpp_mcp.oauth_client import RefreshFailed
from bpp_mcp.token_store import TokenSet

BASE = "https://bpp.test"


def _ts(access="AT", expires_at=None, refresh="RT"):
    return TokenSet(
        base_url=BASE,
        access_token=access,
        refresh_token=refresh,
        expires_at=time.time() + 3600 if expires_at is None else expires_at,
        token_endpoint=f"{BASE}/o/token/",
        username="k",
        client_id="CID",
    )


@pytest.mark.asyncio
async def test_brak_tokenu_none():
    prov = login_state.TokenProvider(BASE)
    assert await prov.bearer() is None


@pytest.mark.asyncio
async def test_wazny_token_zwraca_access():
    token_store.save(_ts(access="WAZNY"))
    prov = login_state.TokenProvider(BASE)
    assert await prov.bearer() == "WAZNY"


@pytest.mark.asyncio
async def test_reload_gdy_login_w_trakcie_sesji():
    # Provider startuje bez tokenu; user robi `bpp-mcp login` później.
    prov = login_state.TokenProvider(BASE)
    assert await prov.bearer() is None
    token_store.save(_ts(access="PO_LOGIN"))
    assert await prov.bearer() == "PO_LOGIN"  # re-load pod lockiem


@pytest.mark.asyncio
async def test_wygasly_odswieza_zapisuje_i_zwraca():
    token_store.save(_ts(access="STARY", expires_at=0.0))
    licznik = {"n": 0}

    def _fake_refresh(ts):
        licznik["n"] += 1
        return _ts(access="NOWY")

    prov = login_state.TokenProvider(BASE, refresh_fn=_fake_refresh)
    assert await prov.bearer() == "NOWY"
    assert licznik["n"] == 1
    assert token_store.load(BASE).access_token == "NOWY"  # rotacja utrwalona


@pytest.mark.asyncio
async def test_rownolegle_bearer_odswieza_raz():
    token_store.save(_ts(access="STARY", expires_at=0.0))
    licznik = {"n": 0}

    def _slow_refresh(ts):
        licznik["n"] += 1
        time.sleep(0.05)
        return _ts(access="NOWY")

    prov = login_state.TokenProvider(BASE, refresh_fn=_slow_refresh)
    wyniki = await asyncio.gather(*(prov.bearer() for _ in range(5)))
    assert wyniki == ["NOWY"] * 5
    assert licznik["n"] == 1  # lock: jeden refresh mimo 5 równoległych wywołań


@pytest.mark.asyncio
async def test_refresh_padl_czysci_i_none():
    token_store.save(_ts(access="STARY", expires_at=0.0))

    def _bad_refresh(ts):
        raise RefreshFailed("invalid_grant")

    prov = login_state.TokenProvider(BASE, refresh_fn=_bad_refresh)
    assert await prov.bearer() is None
    assert token_store.load(BASE) is None  # store wyczyszczony
