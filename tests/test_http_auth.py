import types

import httpx
import pytest

from bpp_mcp import auth
from bpp_mcp.config import Config
from bpp_mcp.server import _auth_kwargs, _client, _http_kwargs, build_mcp

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
    # SDK 2.0 wyjęło host/port z konstruktora — tu ich BYĆ NIE MOŻE, bo
    # MCPServer(host=...) rzuca TypeError.
    assert "host" not in kw and "port" not in kw


def test_http_kwargs_niesie_host_i_port():
    # `host` musi być, nie tylko `port`: run() przekazuje go do
    # streamable_http_app(host=...), skąd bierze się ochrona przed
    # DNS-rebinding opisana w docs/uwierzytelnianie.md. Zgubienie go tutaj
    # wyłączyłoby udokumentowaną własność bezpieczeństwa po cichu.
    assert _http_kwargs(_http_cfg()) == {"host": "127.0.0.1", "port": 8055}


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
async def test_bearer_izolowany_miedzy_rownoleglymi_zadaniami():
    """Dwóch użytkowników naraz nie może zobaczyć swoich tokenów.

    W SDK 1.x lifespan był wchodzony per sesja, więc współdzielenie stanu było
    węższe. W 2.0 wchodzi RAZ i jego wynik dzielą wszystkie sesje i żądania —
    ten sam ``KontekstApp`` obsługuje równolegle różnych użytkowników. Jedyne,
    co trzyma tokeny osobno, to ContextVar ustawiany w ``_client``; asyncio
    daje każdemu zadaniu własną kopię kontekstu. Gdyby ktoś zamienił to na
    zwykły atrybut (choćby na ``KontekstApp``), token jednego użytkownika
    poleciałby do BPP w imieniu drugiego, a ten test jest jedynym miejscem,
    które by to złapało."""
    import asyncio

    from bpp_mcp.server import KontekstApp

    wspolny = KontekstApp(client="SENTINEL", bearer_provider=None)

    async def zadanie(token: str) -> str:
        rc = types.SimpleNamespace(
            request=types.SimpleNamespace(headers={"authorization": f"Bearer {token}"}),
            lifespan_context=wspolny,
        )
        await _client(types.SimpleNamespace(request_context=rc))
        # Oddaj sterowanie, żeby oba zadania faktycznie się przeplotły —
        # bez tego każde przebiegłoby do końca i test przechodziłby nawet
        # przy współdzielonym stanie.
        await asyncio.sleep(0)
        return auth.current_bearer()

    a, b = await asyncio.gather(zadanie("TOKEN_A"), zadanie("TOKEN_B"))
    assert (a, b) == ("TOKEN_A", "TOKEN_B")


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
    # SDK 2.0 nie dokleja już ukośnika do URL bez ścieżki (AuthSettings ma
    # url_preserve_empty_path=True), więc issuer wychodzi dokładnie taki, jaki
    # podaliśmy — bez normalizacji w drugą stronę.
    assert BASE in body["authorization_servers"]
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
async def test_proxy_serwuje_metadane_as():
    from bpp_mcp.oauth_client import AuthMode

    app = build_mcp(_http_cfg(), AuthMode.PROXY).streamable_http_app()
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://testserver"
    ) as c:
        resp = await c.get("/.well-known/oauth-authorization-server")
    assert resp.status_code == 200
    body = resp.json()
    assert body["issuer"] == "http://127.0.0.1:8055"
    assert body["authorization_endpoint"] == f"{BASE}/o/authorize/"
    assert body["token_endpoint"] == f"{BASE}/o/token/"


@pytest.mark.asyncio
async def test_proxy_metadane_as_maja_cors():
    # Bez ACAO klient przeglądarkowy (zdalny connector) padłby na kroku 2
    # discovery — SOP zablokowałby odczyt. SDK daje to samo dla PRM.
    from bpp_mcp.oauth_client import AuthMode

    app = build_mcp(_http_cfg(), AuthMode.PROXY).streamable_http_app()
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://testserver"
    ) as c:
        resp = await c.get(
            "/.well-known/oauth-authorization-server",
            headers={"Origin": "https://claude.ai"},
        )
    assert resp.status_code == 200
    assert resp.headers.get("access-control-allow-origin") == "*"


@pytest.mark.asyncio
async def test_proxy_prm_wskazuje_na_self():
    from bpp_mcp.oauth_client import AuthMode

    app = build_mcp(_http_cfg(), AuthMode.PROXY).streamable_http_app()
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://testserver"
    ) as c:
        resp = await c.get("/.well-known/oauth-protected-resource/mcp")
    assert resp.status_code == 200
    # Sedno RFC 8414 §3.3: PRM i dokument AS muszą podawać ten sam issuer bajt
    # w bajt. Ten test jest detektorem rozjazdu — pilnuje, że obie wartości
    # pochodzą z jednego AuthSettings, a nie z dwóch normalizacji, które ktoś
    # musi pamiętać, by trzymać w zgodzie (tak pękło przy porcie na SDK 2.0).
    assert "http://127.0.0.1:8055" in resp.json()["authorization_servers"]


@pytest.mark.asyncio
async def test_passthrough_brak_trasy_as():
    from bpp_mcp.oauth_client import AuthMode

    app = build_mcp(_http_cfg(), AuthMode.PASSTHROUGH).streamable_http_app()
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://testserver"
    ) as c:
        resp = await c.get("/.well-known/oauth-authorization-server")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_whoami_unavailable_daje_5xx_nie_401():
    from mcp.server.auth.settings import AuthSettings
    from mcp.server.mcpserver import MCPServer

    from bpp_mcp.auth import WhoamiUnavailable

    class Rzucacz:
        async def verify_token(self, token):
            raise WhoamiUnavailable("down")

    srv = MCPServer(
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
