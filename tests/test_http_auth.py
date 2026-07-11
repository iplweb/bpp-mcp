import types

import httpx
import pytest

from bpp_mcp import auth
from bpp_mcp.config import Config
from bpp_mcp.server import _auth_kwargs, _client, build_mcp

BASE = "https://bpp.example.test"
RESOURCE = "http://127.0.0.1:8055/mcp"


def _http_cfg():
    return Config(
        base_url=BASE, transport="http", http_host="127.0.0.1", http_port=8055
    )


def test_auth_kwargs_stdio_puste():
    assert _auth_kwargs(Config(base_url=BASE)) == {}


def test_auth_kwargs_http():
    kw = _auth_kwargs(_http_cfg())
    assert "token_verifier" in kw and "auth" in kw
    assert kw["host"] == "127.0.0.1" and kw["port"] == 8055


@pytest.mark.asyncio
async def test_client_ustawia_bearer_z_biezacego_requestu():
    # K1-guard: _client bierze token z ctx.request_context.request (nie
    # z get_access_token, który jest stale).
    from bpp_mcp.server import KontekstApp

    auth.set_current_bearer(None)
    req = types.SimpleNamespace(headers={"authorization": "Bearer TOKEN_XYZ"})
    rc = types.SimpleNamespace(
        request=req,
        lifespan_context=KontekstApp(client="SENTINEL", bearer_provider=None),
    )
    ctx = types.SimpleNamespace(request_context=rc)
    assert await _client(ctx) == "SENTINEL"
    assert auth.current_bearer() == "TOKEN_XYZ"
    auth.set_current_bearer(None)


@pytest.mark.asyncio
async def test_protected_resource_metadata():
    app = build_mcp(_http_cfg()).streamable_http_app()
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://testserver"
    ) as c:
        # resource_url ma /mcp → PRM pod ścieżką path-inserted (RFC 9728).
        resp = await c.get("/.well-known/oauth-protected-resource/mcp")
    assert resp.status_code == 200
    body = resp.json()
    # AnyHttpUrl normalizuje issuer do trailing slash.
    assert f"{BASE}/" in body["authorization_servers"]
    assert body["resource"] == RESOURCE


@pytest.mark.asyncio
async def test_brak_tokenu_401_z_resource_metadata():
    app = build_mcp(_http_cfg()).streamable_http_app()
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://testserver"
    ) as c:
        resp = await c.post("/mcp", json={"jsonrpc": "2.0", "method": "ping", "id": 1})
    assert resp.status_code == 401
    # resource_metadata w WWW-Authenticate napędza discovery klienta.
    assert "resource_metadata" in resp.headers.get("WWW-Authenticate", "")


@pytest.mark.asyncio
async def test_whoami_unavailable_daje_5xx_nie_401():
    from mcp.server.auth.settings import AuthSettings
    from mcp.server.fastmcp import FastMCP

    from bpp_mcp.auth import WhoamiUnavailable

    class Rzucacz:
        async def verify_token(self, token):
            raise WhoamiUnavailable("down")

    srv = FastMCP(
        "bpp-mcp",
        token_verifier=Rzucacz(),
        auth=AuthSettings(
            issuer_url=BASE,
            resource_server_url=RESOURCE,
            required_scopes=["read"],
        ),
    )
    app = srv.streamable_http_app()
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://testserver"
    ) as c:
        resp = await c.post(
            "/mcp",
            json={"jsonrpc": "2.0", "method": "ping", "id": 1},
            headers={
                "Authorization": "Bearer X",
                "Accept": "application/json, text/event-stream",
                "Content-Type": "application/json",
            },
        )
    assert resp.status_code >= 500
    assert resp.status_code != 401
