# bpp-mcp OAuth 2.1 Resource Server — Implementation Plan (v2)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Dodać `bpp-mcp` tryb Streamable HTTP z OAuth 2.1 (Resource Server): klient MCP (Claude) loguje się do BPP, `bpp-mcp` weryfikuje token przez `whoami` i forwarduje **token bieżącego requestu** do `/api/v1/`. Tryb stdio (anonimowy) zostaje bez zmian.

**Architecture:** OAuth Resource Server na FastMCP. Weryfikacja opaque tokenu przez `WhoamiTokenVerifier`. FastMCP serwuje `/.well-known/oauth-protected-resource` + 401/`WWW-Authenticate`. Bearer bieżącego requestu wyłuskiwany z `ctx.request_context.request` w chokepoincie `_client(ctx)`, przekazywany do `BppClient` przez ContextVar. Server budowany fabryką `build_mcp(config)` z lifespanem związanym z tym samym `config`.

**Tech Stack:** Python ≥3.10, `mcp[cli]>=1.28`, httpx (async), respx (test), pytest.

## Rewizja po review Fable (WIĄŻĄCE — wnioski z 2× adversarial review, zweryfikowane sondą na mcp 1.28.1)

- **K1:** `get_access_token()` w narzędziu zwraca token z chwili `initialize` (stale w stateful HTTP) — POTWIERDZONE sondą. Bearer bierzemy z `ctx.request_context.request` (per-request) w `_client(ctx)` → ContextVar → `BppClient`. Nie używamy `get_access_token()` do passthrough.
- **W2:** `lifespan` MUSI używać `config` przekazanego do `build_mcp` (nie `Config.from_env()`), inaczej token idzie do env-defaultu (wyciek do innej instancji). Lifespan = closure w `build_mcp`.
- **W3:** default `effective_resource_url` zawiera ścieżkę `/mcp` (kanoniczny URI serwera streamable). PRM ląduje wtedy pod `/.well-known/oauth-protected-resource/mcp`.
- **W4:** w trybie `http` brak bearera w kontekście = twardy błąd (NIE cichy fallback na Basic/anon — to podmiana tożsamości na konto serwisowe). Basic tylko w stdio.
- **W1:** `WhoamiUnavailable` z verify_token materializuje się jako **HTTP 500** (Starlette `AuthenticationMiddleware` przepuszcza nie-`AuthenticationError` do `ServerErrorMiddleware`). Semantyka „BPP-down ≠ re-auth" zachowana (500 ≠ 401). Jawne 502/503 = future refinement (poza MVP). Test: verifier rzuca → status `>= 500` i `!= 401`.
- **W5:** positive-cache ma eviction (usuń wygasłe) + twardy cap (256, drop najstarszego).
- **D1:** `verify_token` obejmuje `follow_redirects` + wszystkie nie-200/401/403 → `WhoamiUnavailable`, nie-JSON → `WhoamiUnavailable`.
- **D2:** modułowy `mcp` budowany ZAWSZE jako stdio (`replace(cfg, transport="stdio")`) — niezależny od env `BPP_MCP_TRANSPORT` (inaczej `test_server.py` zależy od env).

## Global Constraints

- Max długość linii **88** (ruff, `select` zawiera `F` i `E` → F401/E501 aktywne — zero nieużywanych importów).
- Wszystkie komendy Pythona przez **`uv run`**.
- **Żadnego bare `except`** — wąskie typy + re-raise/log.
- Testy: **pytest**, funkcje bez klas, `respx` do mocków httpx; testy async wymagają `@pytest.mark.asyncio` (anyio/asyncio mode wg conftest repo).
- Floor SDK: **`mcp[cli]>=1.28.0`** (`TokenVerifier`/RS-auth; potwierdzone na 1.28.1).
- Docstringi/komentarze po polsku.
- Kontrakt BPP (z `dev`): issuer = root `BPP_BASE_URL`; `whoami` = `GET /api/v1/whoami/` → 200 `{id,username,is_staff,is_superuser}` | 401; scope `read`; token opaque; write→403; DCR dopuszcza `http://localhost:*`/`http://127.0.0.1:*`.

---

### Task 1: Bump SDK + rozszerzenie Config

**Files:**
- Modify: `pyproject.toml`
- Modify: `src/bpp_mcp/config.py`
- Create: `tests/test_config.py` (plik NIE istnieje — utwórz)

**Interfaces:**
- Produces: `Config` z polami `transport: str="stdio"`, `http_host: str="127.0.0.1"`, `http_port: int=8000`, `resource_url: str | None=None` + property `effective_resource_url -> str` (**z sufiksem `/mcp`** gdy brak override). `from_env()` czyta `BPP_MCP_TRANSPORT`, `BPP_MCP_HTTP_HOST`, `BPP_MCP_HTTP_PORT`, `BPP_MCP_RESOURCE_URL`.

- [ ] **Step 1: Podnieś floor SDK**

W `pyproject.toml` zmień `"mcp[cli]>=1.2.0",` na `"mcp[cli]>=1.28.0",`. Uruchom `uv lock && uv sync`. Oczekiwane: brak błędów.

- [ ] **Step 2: Utwórz `tests/test_config.py` (failujący)**

```python
from bpp_mcp.config import Config


def test_from_env_transport_defaults(monkeypatch):
    for k in ("BPP_MCP_TRANSPORT", "BPP_MCP_HTTP_HOST",
              "BPP_MCP_HTTP_PORT", "BPP_MCP_RESOURCE_URL"):
        monkeypatch.delenv(k, raising=False)
    cfg = Config.from_env()
    assert cfg.transport == "stdio"
    assert cfg.http_host == "127.0.0.1"
    assert cfg.http_port == 8000
    assert cfg.effective_resource_url == "http://127.0.0.1:8000/mcp"


def test_from_env_transport_http(monkeypatch):
    monkeypatch.setenv("BPP_MCP_TRANSPORT", "HTTP")
    monkeypatch.setenv("BPP_MCP_HTTP_PORT", "9123")
    monkeypatch.delenv("BPP_MCP_RESOURCE_URL", raising=False)
    cfg = Config.from_env()
    assert cfg.transport == "http"
    assert cfg.http_port == 9123
    assert cfg.effective_resource_url == "http://127.0.0.1:9123/mcp"


def test_resource_url_override(monkeypatch):
    monkeypatch.setenv("BPP_MCP_RESOURCE_URL", "http://127.0.0.1:9000/mcp")
    cfg = Config.from_env()
    assert cfg.effective_resource_url == "http://127.0.0.1:9000/mcp"
```

- [ ] **Step 3: Uruchom — ma failować**

Run: `uv run pytest tests/test_config.py -q` → FAIL (`transport`/`effective_resource_url` nie istnieją).

- [ ] **Step 4: Rozszerz `Config`**

W `src/bpp_mcp/config.py` dodaj pola do dataclass (po `basic_auth`):

```python
    transport: str = "stdio"
    http_host: str = "127.0.0.1"
    http_port: int = 8000
    resource_url: str | None = None

    @property
    def effective_resource_url(self) -> str:
        """URL zasobu (pole ``resource`` w protected-resource-metadata).
        Domyślnie kanoniczny URI serwera streamable: host:port + ``/mcp``."""
        return self.resource_url or f"http://{self.http_host}:{self.http_port}/mcp"
```

Zastąp `return cls(base_url=base, basic_auth=auth)` w `from_env`:

```python
        transport = os.environ.get("BPP_MCP_TRANSPORT", "stdio").lower()
        return cls(
            base_url=base,
            basic_auth=auth,
            transport="http" if transport == "http" else "stdio",
            http_host=os.environ.get("BPP_MCP_HTTP_HOST", "127.0.0.1"),
            http_port=int(os.environ.get("BPP_MCP_HTTP_PORT", "8000")),
            resource_url=os.environ.get("BPP_MCP_RESOURCE_URL") or None,
        )
```

(Nieznana wartość `BPP_MCP_TRANSPORT` → `stdio` — świadomy, bezpieczny default.)

- [ ] **Step 5: Uruchom — ma przejść**

Run: `uv run pytest tests/test_config.py -q` → PASS.

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml uv.lock src/bpp_mcp/config.py tests/test_config.py
git commit -m "feat(config): transport/http/resource(+/mcp) + bump mcp>=1.28"
```

---

### Task 2: auth.py — WhoamiTokenVerifier + ContextVar bearer + cache z eviction

**Files:**
- Create: `src/bpp_mcp/auth.py`
- Test: `tests/test_auth.py`

**Interfaces:**
- Consumes: `Config.base_url`.
- Produces:
  - `class WhoamiUnavailable(Exception)`.
  - `class WhoamiTokenVerifier` (`TokenVerifier`): `WhoamiTokenVerifier(base_url: str, *, ttl: float = 30.0, max_entries: int = 256)`; `async def verify_token(self, token: str) -> AccessToken | None`.
  - `def bearer_from_request(request) -> str | None` — wyłuskaj `Bearer` z nagłówka `Authorization` (request Starlette albo `None`).
  - `def set_current_bearer(token: str | None) -> None` / `def current_bearer() -> str | None` — ContextVar mostu do `BppClient` (NIE `get_access_token()` — patrz K1).

- [ ] **Step 1: Testy (failujące)**

Utwórz `tests/test_auth.py`:

```python
import httpx
import pytest
import respx

from bpp_mcp.auth import (
    WhoamiTokenVerifier,
    WhoamiUnavailable,
    bearer_from_request,
    current_bearer,
    set_current_bearer,
)

BASE = "https://bpp.example.test"
WHOAMI = f"{BASE}/api/v1/whoami/"


@pytest.mark.asyncio
@respx.mock
async def test_valid_token():
    respx.get(WHOAMI).mock(return_value=httpx.Response(
        200, json={"id": 7, "username": "kowalski"}))
    tok = await WhoamiTokenVerifier(BASE).verify_token("OPAQUE")
    assert tok is not None
    assert tok.token == "OPAQUE"
    assert tok.scopes == ["read"]
    assert tok.subject == "7"


@pytest.mark.asyncio
@respx.mock
async def test_invalid_token_none():
    respx.get(WHOAMI).mock(return_value=httpx.Response(401))
    assert await WhoamiTokenVerifier(BASE).verify_token("ZLY") is None


@pytest.mark.asyncio
@respx.mock
async def test_5xx_unavailable():
    respx.get(WHOAMI).mock(return_value=httpx.Response(503))
    with pytest.raises(WhoamiUnavailable):
        await WhoamiTokenVerifier(BASE).verify_token("OPAQUE")


@pytest.mark.asyncio
@respx.mock
async def test_siec_unavailable():
    respx.get(WHOAMI).mock(side_effect=httpx.ConnectError("down"))
    with pytest.raises(WhoamiUnavailable):
        await WhoamiTokenVerifier(BASE).verify_token("OPAQUE")


@pytest.mark.asyncio
@respx.mock
async def test_niejson_unavailable():
    respx.get(WHOAMI).mock(return_value=httpx.Response(200, text="nie-json"))
    with pytest.raises(WhoamiUnavailable):
        await WhoamiTokenVerifier(BASE).verify_token("OPAQUE")


@pytest.mark.asyncio
@respx.mock
async def test_cache_hit_w_ttl():
    route = respx.get(WHOAMI).mock(return_value=httpx.Response(
        200, json={"id": 1, "username": "a"}))
    v = WhoamiTokenVerifier(BASE, ttl=60.0)
    await v.verify_token("T")
    await v.verify_token("T")
    assert route.call_count == 1


@pytest.mark.asyncio
@respx.mock
async def test_ttl_0_reweryfikuje():
    route = respx.get(WHOAMI).mock(return_value=httpx.Response(
        200, json={"id": 1, "username": "a"}))
    v = WhoamiTokenVerifier(BASE, ttl=0.0)
    await v.verify_token("T")
    await v.verify_token("T")
    assert route.call_count == 2


def test_bearer_from_request_i_contextvar():
    class Req:
        headers = {"authorization": "Bearer ABC"}
    assert bearer_from_request(Req()) == "ABC"
    assert bearer_from_request(None) is None
    set_current_bearer("XYZ")
    assert current_bearer() == "XYZ"
    set_current_bearer(None)
    assert current_bearer() is None
```

- [ ] **Step 2: Uruchom — ma failować**

Run: `uv run pytest tests/test_auth.py -q` → FAIL (`ModuleNotFoundError`).

- [ ] **Step 3: Zaimplementuj `src/bpp_mcp/auth.py`**

```python
"""Warstwa OAuth Resource Server: weryfikacja opaque tokenu BPP przez
``whoami`` oraz przekazanie tokenu BIEŻĄCEGO requestu do BppClient.

Token BPP jest OPAQUE (nie JWT) — weryfikacja tylko zdalnie przez
``GET /api/v1/whoami/``: 200 → ważny, 401/403 → nieważny (``None`` →
transportowy 401), inne/sieć/nie-JSON → :class:`WhoamiUnavailable` (BPP
niedostępne; materializuje się jako HTTP 500 — klient NIE robi re-auth).

UWAGA (K1): do passthrough NIE używamy ``get_access_token()`` — w stateful
streamable HTTP zwraca on token z chwili ``initialize`` (stale). Token
bieżącego requestu bierzemy z ``ctx.request_context.request`` (patrz
``server._client``) i mostkujemy przez ContextVar poniżej.
"""

from __future__ import annotations

import time
from contextvars import ContextVar

import httpx
from mcp.server.auth.provider import AccessToken

_current_bearer: ContextVar[str | None] = ContextVar(
    "bpp_mcp_current_bearer", default=None
)


class WhoamiUnavailable(Exception):
    """BPP niedostępne przy weryfikacji tokenu (nie-200/401/403, sieć, nie-JSON).

    Różne od ``None`` (token nieważny → re-auth): token mógł być ważny, więc
    nie wymuszamy re-autoryzacji — request kończy się błędem serwera (5xx).
    """


def set_current_bearer(token: str | None) -> None:
    """Zapisz token bieżącego requestu w kontekście (dla BppClient)."""
    _current_bearer.set(token)


def current_bearer() -> str | None:
    """Zwróć token bieżącego requestu z kontekstu (``None`` poza http)."""
    return _current_bearer.get()


def bearer_from_request(request) -> str | None:
    """Wyłuskaj surowy token z nagłówka ``Authorization: Bearer`` (lub None)."""
    if request is None:
        return None
    authz = request.headers.get("authorization", "")
    if authz.lower().startswith("bearer "):
        return authz.split(" ", 1)[1].strip()
    return None


class WhoamiTokenVerifier:
    """``TokenVerifier`` (protokół SDK) oparty o ``whoami`` BPP, z positive-cache.

    Cache (``ttl`` s) redukuje +1 request/wywołanie i wygładza blipy; ma eviction
    (usuwa wygasłe) i twardy cap ``max_entries`` (drop najstarszego), by proces
    nie akumulował zrewokowanych tokenów w nieskończoność.
    """

    def __init__(
        self, base_url: str, *, ttl: float = 30.0, max_entries: int = 256
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._ttl = ttl
        self._max_entries = max_entries
        self._cache: dict[str, tuple[AccessToken, float]] = {}

    async def verify_token(self, token: str) -> AccessToken | None:
        now = time.monotonic()
        cached = self._cache.get(token)
        if cached is not None and cached[1] > now:
            return cached[0]
        url = f"{self._base_url}/api/v1/whoami/"
        headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(10.0, connect=5.0), follow_redirects=True
            ) as client:
                resp = await client.get(url, headers=headers)
        except httpx.HTTPError as exc:
            raise WhoamiUnavailable(f"whoami niedostępne: {exc}") from exc
        if resp.status_code in (401, 403):
            return None
        if resp.status_code != 200:
            raise WhoamiUnavailable(f"whoami zwróciło {resp.status_code}")
        try:
            data = resp.json()
        except ValueError as exc:
            raise WhoamiUnavailable(f"whoami zwróciło nie-JSON: {exc}") from exc
        access = AccessToken(
            token=token,
            client_id="bpp-mcp",
            scopes=["read"],
            subject=str(data["id"]) if data.get("id") is not None else None,
            claims=data,
        )
        self._store(token, access, now)
        return access

    def _store(self, token: str, access: AccessToken, now: float) -> None:
        if len(self._cache) >= self._max_entries:
            for k in [k for k, (_, exp) in self._cache.items() if exp <= now]:
                del self._cache[k]
            while len(self._cache) >= self._max_entries:
                self._cache.pop(next(iter(self._cache)))
        self._cache[token] = (access, now + self._ttl)
```

- [ ] **Step 4: Uruchom — ma przejść**

Run: `uv run pytest tests/test_auth.py -q` → PASS (8 passed).

- [ ] **Step 5: Commit**

```bash
git add src/bpp_mcp/auth.py tests/test_auth.py
git commit -m "feat(auth): WhoamiTokenVerifier + ContextVar bearer + cache eviction"
```

---

### Task 3: BppClient — passthrough bieżącego Bearera (Bearer > [stdio: Basic > anon]; http bez bearera = błąd)

**Files:**
- Modify: `src/bpp_mcp/client.py` (import, `__init__:56-74`, nowa metoda, `_request:98-135`)
- Test: `tests/test_client_auth.py`

**Interfaces:**
- Consumes: `current_bearer()`, `Config.auth_tuple`, `Config.transport`.
- Produces: `BppClient` wysyła `Authorization: Bearer <current_bearer()>` gdy jest; w stdio bez bearera → Basic (gdy `auth_tuple`) lub anonimowo; **w http bez bearera → `BppError`** (bez podmiany na konto serwisowe).

- [ ] **Step 1: Testy (failujące)**

Utwórz `tests/test_client_auth.py`:

```python
import httpx
import pytest
import respx

from bpp_mcp import auth
from bpp_mcp.client import BppError, BppClient
from bpp_mcp.config import Config

BASE = "https://bpp.example.test"
PING = f"{BASE}/api/v1/uczelnia/1/"


def _cfg(basic=None, transport="stdio"):
    return Config(base_url=BASE, basic_auth=basic, transport=transport)


@pytest.fixture(autouse=True)
def _czysty_bearer():
    auth.set_current_bearer(None)
    yield
    auth.set_current_bearer(None)


@pytest.mark.asyncio
@respx.mock
async def test_bearer_forwardowany():
    auth.set_current_bearer("TESTTOKEN")
    route = respx.get(PING).mock(return_value=httpx.Response(200, json={"ok": 1}))
    async with BppClient(_cfg(transport="http")) as c:
        await c.get_json("uczelnia/1/")
    assert route.calls.last.request.headers["Authorization"] == "Bearer TESTTOKEN"


@pytest.mark.asyncio
@respx.mock
async def test_stdio_bez_bearera_anon():
    route = respx.get(PING).mock(return_value=httpx.Response(200, json={"ok": 1}))
    async with BppClient(_cfg()) as c:
        await c.get_json("uczelnia/1/")
    assert "Authorization" not in route.calls.last.request.headers


@pytest.mark.asyncio
@respx.mock
async def test_stdio_basic_gdy_brak_bearera():
    route = respx.get(PING).mock(return_value=httpx.Response(200, json={"ok": 1}))
    async with BppClient(_cfg(basic="u:p")) as c:
        await c.get_json("uczelnia/1/")
    # Basic base64("u:p") == "dTpw"
    assert route.calls.last.request.headers["Authorization"] == "Basic dTpw"


@pytest.mark.asyncio
@respx.mock
async def test_http_bez_bearera_blad():
    respx.get(PING).mock(return_value=httpx.Response(200, json={"ok": 1}))
    async with BppClient(_cfg(basic="u:p", transport="http")) as c:
        with pytest.raises(BppError):
            await c.get_json("uczelnia/1/")
```

- [ ] **Step 2: Uruchom — ma failować**

Run: `uv run pytest tests/test_client_auth.py -q` → FAIL.

- [ ] **Step 3: Zmodyfikuj `client.py`**

Dodaj import (po `import httpx`):

```python
from .auth import current_bearer
```

W `__init__` USUŃ `auth=config.auth_tuple,` z `httpx.AsyncClient(...)`, ZAPISZ tuple i transport:

```python
        self._auth_tuple = config.auth_tuple
        self._transport = config.transport
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(10.0, connect=5.0),
            headers={"Accept": "application/json"},
            follow_redirects=True,
        )
```

Dodaj metodę (nad `_request`):

```python
    def _auth_kwargs(self) -> dict[str, Any]:
        """Per-request auth. Bearer (bieżący request) wygrywa zawsze. W trybie
        http brak bearera = błąd (żadnego cichego fallbacku na konto serwisowe).
        W stdio: Basic (gdy skonfigurowany) albo anonimowo."""
        bearer = current_bearer()
        if bearer:
            return {"headers": {"Authorization": f"Bearer {bearer}"}}
        if self._transport == "http":
            raise BppError(
                "Brak tokenu OAuth w kontekście żądania (tryb http) — nie "
                "forwarduję anonimowo ani przez konto serwisowe."
            )
        if self._auth_tuple:
            return {"auth": self._auth_tuple}
        return {}
```

W `_request`, PRZED pętlą `for proba...`, policz auth raz i użyj w GET:

```python
        auth_kwargs = self._auth_kwargs()
        ostatni: Exception | None = None
        for proba in range(self._max_retries + 1):
            async with self._sem:
                try:
                    resp = await self._client.get(full, **auth_kwargs)
```

- [ ] **Step 4: Uruchom — ma przejść**

Run: `uv run pytest tests/test_client_auth.py -q` → PASS (4 passed).

- [ ] **Step 5: Regres**

Run: `uv run pytest -q` → PASS (istniejące testy klienta/narzędzi bez zmian; działają w trybie stdio → brak bearera → anon jak dziś).

- [ ] **Step 6: Commit**

```bash
git add src/bpp_mcp/client.py tests/test_client_auth.py
git commit -m "feat(client): passthrough bieżącego Bearera; http bez bearera = błąd"
```

---

### Task 4: server.py — fabryka build_mcp (lifespan związany z config) + HTTP + auth + CLI + chokepoint bearera

**Files:**
- Modify: `src/bpp_mcp/server.py`
- Test: `tests/test_http_auth.py`

**Interfaces:**
- Consumes: `WhoamiTokenVerifier`, `bearer_from_request`, `set_current_bearer` (Task 2); rozszerzony `Config` (Task 1).
- Produces: `build_mcp(config) -> FastMCP`, `_auth_kwargs(config) -> dict`, `_client(ctx)` (ustawia bearer z bieżącego requestu), modułowy `mcp` (ZAWSZE stdio), `main()` z `--http/--host/--port`.

- [ ] **Step 1: Testy (failujące)**

Utwórz `tests/test_http_auth.py`:

```python
import types

import httpx
import pytest

from bpp_mcp import auth
from bpp_mcp.config import Config
from bpp_mcp.server import _auth_kwargs, _client, build_mcp

BASE = "https://bpp.example.test"


def _http_cfg():
    return Config(base_url=BASE, transport="http",
                  http_host="127.0.0.1", http_port=8055)


def test_auth_kwargs_stdio_puste():
    assert _auth_kwargs(Config(base_url=BASE)) == {}


def test_auth_kwargs_http():
    kw = _auth_kwargs(_http_cfg())
    assert "token_verifier" in kw and "auth" in kw
    assert kw["host"] == "127.0.0.1" and kw["port"] == 8055


def test_client_ustawia_bearer_z_biezacego_requestu():
    # K1-guard: _client bierze token z ctx.request_context.request (nie
    # z get_access_token, który jest stale).
    auth.set_current_bearer(None)
    req = types.SimpleNamespace(headers={"authorization": "Bearer TOKEN_XYZ"})
    rc = types.SimpleNamespace(
        request=req,
        lifespan_context=types.SimpleNamespace(client="SENTINEL"),
    )
    ctx = types.SimpleNamespace(request_context=rc)
    assert _client(ctx) == "SENTINEL"
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
    assert body["resource"] == "http://127.0.0.1:8055/mcp"


@pytest.mark.asyncio
async def test_brak_tokenu_401_z_resource_metadata():
    app = build_mcp(_http_cfg()).streamable_http_app()
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://testserver"
    ) as c:
        resp = await c.post("/mcp", json={"jsonrpc": "2.0", "method": "ping",
                                          "id": 1})
    assert resp.status_code == 401
    # resource_metadata w WWW-Authenticate napędza discovery klienta.
    assert "resource_metadata" in resp.headers.get("WWW-Authenticate", "")
```

- [ ] **Step 2: Uruchom — ma failować**

Run: `uv run pytest tests/test_http_auth.py -q` → FAIL (`_auth_kwargs`/`build_mcp`/`_client` refaktor).

- [ ] **Step 3: Zrefaktoryzuj `server.py`**

1. Usuń dekoratory `@mcp.tool()` / `@mcp.prompt(...)` znad 8 funkcji narzędzi i `zloz_zapytanie_djangoql` (same funkcje + `PROMPT_ZLOZ_ZAPYTANIE` bez zmian, zostają importowalne).
2. Usuń modułowe `mcp = FastMCP(...)` (linia 35) ORAZ dotychczasowy `lifespan`/`KontekstApp` przenieś logikę do fabryki (patrz niżej).
3. Importy na górze (po istniejących):

```python
import argparse
from dataclasses import replace

from mcp.server.auth.settings import AuthSettings

from .auth import WhoamiTokenVerifier, bearer_from_request, set_current_bearer
```

4. Zmień `_client` tak, by ustawiał bearer bieżącego requestu (K1):

```python
def _client(ctx: Context) -> BppClient:
    """Zwróć współdzielony klient ORAZ ustaw w kontekście token bieżącego
    requestu (z ctx.request_context.request — NIE get_access_token, K1)."""
    request = getattr(ctx.request_context, "request", None)
    set_current_bearer(bearer_from_request(request))
    return ctx.request_context.lifespan_context.client
```

5. Na końcu pliku (po `PROMPT_ZLOZ_ZAPYTANIE` i funkcjach) dodaj:

```python
def _register(mcp: FastMCP) -> None:
    """Zarejestruj 8 narzędzi + prompt na danej instancji FastMCP."""
    mcp.tool()(szukaj_publikacji)
    mcp.tool()(szukaj_autora)
    mcp.tool()(publikacje_autora)
    mcp.tool()(publikacje_jednostki)
    mcp.tool()(pobierz_rekord)
    mcp.tool()(lista_publikacji)
    mcp.tool()(slownik)
    mcp.tool()(djangoql_schema)
    mcp.prompt(
        name="zloz_zapytanie_djangoql",
        description=(
            "Ułóż (nie wykonuj) zapytanie DjangoQL dla modelu bpp.Rekord na "
            "podstawie opisu po polsku — do wklejenia w edytor „zapytanie” BPP."
        ),
    )(zloz_zapytanie_djangoql)


def _auth_kwargs(config: Config) -> dict[str, Any]:
    """Argumenty auth do FastMCP: puste w stdio; w http token_verifier +
    AuthSettings (RS) + host/port."""
    if config.transport != "http":
        return {}
    return {
        "token_verifier": WhoamiTokenVerifier(config.base_url),
        "auth": AuthSettings(
            issuer_url=config.base_url,
            resource_server_url=config.effective_resource_url,
            required_scopes=["read"],
        ),
        "host": config.http_host,
        "port": config.http_port,
    }


def build_mcp(config: Config) -> FastMCP:
    """Zbuduj serwer FastMCP. Lifespan zakłada BppClient związany z TYM config
    (W2 — nie z env), więc verifier i klient używają tej samej instancji BPP."""

    @asynccontextmanager
    async def lifespan(_server: FastMCP) -> AsyncIterator[KontekstApp]:
        client = BppClient(config)
        try:
            yield KontekstApp(client=client)
        finally:
            await client.aclose()

    mcp = FastMCP("bpp-mcp", lifespan=lifespan, **_auth_kwargs(config))
    _register(mcp)
    return mcp


# Modułowy serwer — ZAWSZE stdio (D2: niezależny od env BPP_MCP_TRANSPORT),
# używany przez stdio-entry i istniejące testy importujące ``mcp``.
mcp = build_mcp(replace(Config.from_env(), transport="stdio"))


def main() -> None:
    """``bpp-mcp``: bez flag → stdio (anon/Basic); ``--http`` → Streamable HTTP
    + OAuth (Resource Server)."""
    parser = argparse.ArgumentParser(prog="bpp-mcp")
    parser.add_argument("--http", action="store_true",
                        help="Streamable HTTP + OAuth (Resource Server).")
    parser.add_argument("--host", default=None, help="Host HTTP (dom. 127.0.0.1).")
    parser.add_argument("--port", type=int, default=None, help="Port HTTP.")
    args = parser.parse_args()
    config = Config.from_env()
    if args.http:
        config = replace(
            config,
            transport="http",
            http_host=args.host or config.http_host,
            http_port=args.port or config.http_port,
        )
    server = build_mcp(config) if config.transport == "http" else mcp
    if config.transport == "http":
        server.run(transport="streamable-http")
    else:
        server.run()
```

Uwaga: `KontekstApp` (dataclass) i `_client` zostają modułowe; importy `asynccontextmanager`, `AsyncIterator` już są na górze pliku.

- [ ] **Step 4: Uruchom nowe testy — mają przejść**

Run: `uv run pytest tests/test_http_auth.py -q` → PASS (5 passed). Jeśli `test_brak_tokenu...` ≠ 401 — sprawdź, czy `_auth_kwargs` zwraca `token_verifier`+`auth`.

- [ ] **Step 5: Test transportowy „BPP-down → 5xx, nie 401" (W1)**

Dopisz do `tests/test_http_auth.py`:

```python
@pytest.mark.asyncio
async def test_whoami_unavailable_daje_5xx_nie_401():
    from bpp_mcp.auth import WhoamiUnavailable

    class Rzucacz:
        async def verify_token(self, token):
            raise WhoamiUnavailable("down")

    srv = build_mcp(_http_cfg())
    # Podmień verifier na rzucający (RS-mode już ustawiony).
    srv.settings.auth  # sanity: auth aktywne
    srv._token_verifier = Rzucacz()
    app = srv.streamable_http_app()
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://testserver"
    ) as c:
        resp = await c.post(
            "/mcp", json={"jsonrpc": "2.0", "method": "ping", "id": 1},
            headers={"Authorization": "Bearer X",
                     "Accept": "application/json, text/event-stream",
                     "Content-Type": "application/json"})
    assert resp.status_code >= 500
    assert resp.status_code != 401
```

Jeśli podmiana `srv._token_verifier` nie zadziała (inna nazwa atrybutu w SDK) — zbuduj serwer, podając verifier bezpośrednio: skopiuj `_auth_kwargs` i podmień `token_verifier` na `Rzucacz()` przed `FastMCP(...)`. Zweryfikuj nazwę atrybutu: `uv run python -c "from bpp_mcp.server import build_mcp; from bpp_mcp.config import Config; s=build_mcp(Config(base_url='x', transport='http')); print([a for a in vars(s) if 'token' in a.lower()])"`.

Run: `uv run pytest tests/test_http_auth.py -q` → PASS.

- [ ] **Step 6: Regres pełny**

Run: `uv run pytest -q` → PASS (istniejące `test_server.py`/`test_djangoql_schema.py` zielone — modułowy `mcp` stdio, funkcje/prompt/`PROMPT_ZLOZ_ZAPYTANIE` nietknięte).

- [ ] **Step 7: Smoke stdio**

Run: `uv run bpp-mcp --help` → pomoc argparse z `--http`. `BPP_MCP_TRANSPORT=http` w env NIE zmienia modułowego `mcp` (stdio), zmienia tylko `main()` przez `Config.from_env()`.

- [ ] **Step 8: Commit**

```bash
git add src/bpp_mcp/server.py tests/test_http_auth.py
git commit -m "feat(server): build_mcp (lifespan~config) + HTTP + OAuth + CLI + bearer chokepoint"
```

---

### Task 5: README + newsfragment

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Sekcja „Tryb OAuth (HTTP)" w README**

W „Instalacja i uruchomienie" dodaj:

````markdown
### Tryb OAuth (HTTP, per-user)

Domyślnie `bpp-mcp` działa po **stdio** i anonimowo (dane publiczne). Aby działać
**z uprawnieniami zalogowanego użytkownika BPP** (OAuth 2.1):

```bash
BPP_BASE_URL=https://bpp.umlub.pl uv run bpp-mcp --http --port 8000
```

Klient MCP (Claude) sam przeprowadza logowanie: wykrywa serwer autoryzacji BPP
przez `/.well-known/oauth-protected-resource`, rejestruje się (DCR), otwiera
przeglądarkę na logowanie BPP + ekran zgody (scope `read`), po czym wywołuje
narzędzia z `Bearer`. `bpp-mcp` weryfikuje token przez `GET /api/v1/whoami/` i
forwarduje token **bieżącego requestu** do `/api/v1/`. Zapis jest zablokowany
serwerowo (read-only).

Zmienne: `BPP_BASE_URL` (instancja = API i issuer OAuth), `BPP_MCP_TRANSPORT`
(`stdio`|`http`), `BPP_MCP_HTTP_HOST` (dom. `127.0.0.1`), `BPP_MCP_HTTP_PORT`,
`BPP_MCP_RESOURCE_URL` (dom. `http://<host>:<port>/mcp`).

**Bezpieczeństwo:** trzymaj `--host 127.0.0.1` (domyślnie). Bind na inny host
wyłącza wbudowaną ochronę DNS-rebinding SDK i eksponuje serwer poza maszynę.
Token jest forwardowany do API BPP bez wiązania `audience` (świadome odstępstwo
od MCP-MUST: `bpp-mcp` i API BPP = ta sama domena zaufania; mitygacje: scope
`read`, twardy read-only serwerowo, krótki TTL).
````

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "docs(readme): tryb OAuth (HTTP) + nota bezpieczeństwa"
```

---

## Kolejność i zależności

Task 1 → 2 → 3 → 4 → 5. Task 3 importuje `auth.current_bearer`; Task 4 importuje `WhoamiTokenVerifier`/`bearer_from_request`/`set_current_bearer` + rozszerzony `Config`. Każdy task kończy zielonymi testami + commitem.

## Po wdrożeniu

- `uv run pytest -q` — cała suita zielona; `uvx pre-commit run --all-files` — czysto.
- **Manualny e2e smoke** (poza CI, sondą `scratchpad/probe_fix.py` potwierdzono per-request bearer): `bpp-mcp --http` + klient MCP z OAuth; przejść pełny dance; sprawdzić, że po odświeżeniu tokenu w trakcie sesji narzędzia dalej działają (K1) i że próba zapisu → 403.
- Push gałęzi `feat-oauth-resource-server` → PR do `main` z opisem + linkiem do spec/plan.
