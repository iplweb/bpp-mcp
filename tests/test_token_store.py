from __future__ import annotations

import json
import stat

from bpp_mcp import token_store
from bpp_mcp.token_store import TokenSet


def _ts(base="https://bpp.test", **kw):
    d = dict(
        base_url=base,
        access_token="AT",
        refresh_token="RT",
        expires_at=10_000.0,
        token_endpoint=f"{base}/o/token/",
        username="kowalski",
        client_id="CID",
    )
    d.update(kw)
    return TokenSet(**d)


def test_path_per_instancja(tmp_path):
    a = token_store.store_path("https://bpp.umlub.pl")
    b = token_store.store_path("https://bpp.inna.pl")
    assert a != b
    assert a.name == "tokens.json"
    assert str(tmp_path) in str(a)


def test_path_normalizuje_trailing_slash():
    assert token_store.store_path("https://x/") == token_store.store_path("https://x")


def test_save_load_roundtrip():
    ts = _ts()
    token_store.save(ts)
    assert token_store.load(ts.base_url) == ts


def test_save_ustawia_uprawnienia_0600():
    ts = _ts()
    token_store.save(ts)
    path = token_store.store_path(ts.base_url)
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700


def test_save_nadpisuje_utrzymuje_0600():
    token_store.save(_ts(access_token="A"))
    token_store.save(_ts(access_token="B"))
    path = token_store.store_path("https://bpp.test")
    assert token_store.load("https://bpp.test").access_token == "B"
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_load_brak_pliku_none():
    assert token_store.load("https://bpp.test") is None


def test_load_uszkodzony_json_none():
    ts = _ts()
    path = token_store.store_path(ts.base_url)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{ nie-json", encoding="utf-8")
    assert token_store.load(ts.base_url) is None


def test_load_niekompletny_none():
    ts = _ts()
    path = token_store.store_path(ts.base_url)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"base_url": ts.base_url}), encoding="utf-8")
    assert token_store.load(ts.base_url) is None


def test_clear_idempotentny():
    ts = _ts()
    token_store.save(ts)
    token_store.clear(ts.base_url)
    assert token_store.load(ts.base_url) is None
    token_store.clear(ts.base_url)  # drugi raz — bez wyjątku


def test_is_expired_z_wstrzyknietym_now():
    ts = _ts(expires_at=1000.0)
    assert ts.is_expired(now=999.0) is True
    assert ts.is_expired(now=900.0) is False
    assert ts.is_expired(skew=0.0, now=999.0) is False
