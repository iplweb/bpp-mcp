from __future__ import annotations

import pytest

from bpp_mcp import server, token_store
from bpp_mcp.config import Config
from bpp_mcp.token_store import TokenSet

BASE = "https://bpp.test"


@pytest.fixture(autouse=True)
def _base_url(monkeypatch):
    monkeypatch.setenv("BPP_BASE_URL", BASE)


def _ts():
    return TokenSet(
        base_url=BASE,
        access_token="AT",
        refresh_token="RT",
        expires_at=10_000.0,
        token_endpoint=f"{BASE}/o/token/",
        username="dabrowski",
        client_id="CID",
    )


def test_cmd_login_zapisuje_i_drukuje(monkeypatch, capsys):
    def _fake_login(base_url, *, existing_client_id=None):
        assert base_url == BASE
        return _ts()

    monkeypatch.setattr(server.oauth_client, "login", _fake_login)
    server._cmd_login(Config.from_env())
    assert token_store.load(BASE).access_token == "AT"
    out = capsys.readouterr().out
    assert "dabrowski" in out
    assert "AT" not in out and "RT" not in out  # anty-wyciek tokenu


def test_cmd_login_reuzywa_client_id(monkeypatch):
    token_store.save(_ts())  # ma client_id=CID
    widziane = {}

    def _fake_login(base_url, *, existing_client_id=None):
        widziane["cid"] = existing_client_id
        return _ts()

    monkeypatch.setattr(server.oauth_client, "login", _fake_login)
    server._cmd_login(Config.from_env())
    assert widziane["cid"] == "CID"


def test_cmd_login_blad_systemexit(monkeypatch):
    def _boom(base_url, *, existing_client_id=None):
        raise TimeoutError("brak callbacku")

    monkeypatch.setattr(server.oauth_client, "login", _boom)
    with pytest.raises(SystemExit):
        server._cmd_login(Config.from_env())


def test_main_login(monkeypatch):
    called = {}

    def _fake(cfg):
        called["login"] = cfg

    monkeypatch.setattr(server, "_cmd_login", _fake)
    monkeypatch.setattr("sys.argv", ["bpp-mcp", "login"])
    server.main()
    assert "login" in called


def test_main_logout_czysci(monkeypatch):
    token_store.save(_ts())
    monkeypatch.setattr("sys.argv", ["bpp-mcp", "logout"])
    server.main()
    assert token_store.load(BASE) is None


def test_main_bez_podkomendy_uruchamia_serwer(monkeypatch):
    uruchomiono = {}

    def _run(*a, **k):
        uruchomiono["run"] = True

    monkeypatch.setattr("sys.argv", ["bpp-mcp"])
    monkeypatch.setattr(server.mcp, "run", _run)
    server.main()
    assert uruchomiono.get("run") is True
