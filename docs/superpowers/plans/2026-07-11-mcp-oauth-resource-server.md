# bpp-mcp OAuth 2.1 Resource Server — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Dodać `bpp-mcp` tryb Streamable HTTP z OAuth 2.1 (Resource Server), w którym klient MCP (Claude) loguje się do BPP, a `bpp-mcp` weryfikuje token przez `whoami` i forwarduje go do `/api/v1/`. Tryb stdio (anonimowy) zostaje bez zmian.

**Architecture:** `bpp-mcp` = OAuth Resource Server na FastMCP. Weryfikacja opaque tokenu przez własny `WhoamiTokenVerifier` (woła `GET {BPP}/api/v1/whoami/`). FastMCP sam serwuje `/.well-known/oauth-protected-resource` i zwraca 401+`WWW-Authenticate`. `BppClient` forwarduje `Bearer` z kontekstu auth SDK. Wybór transportu env/CLI; server budowany fabryką `build_mcp(config)`.

**Tech Stack:** Python ≥3.10, `mcp[cli]` (FastMCP + `TokenVerifier`/`AuthSettings`), httpx (async), respx (test), pytest.

## Global Constraints

- Max długość linii **88** (ruff).
- Wszystkie komendy Pythona przez **`uv run`**.
- **Żadnego bare `except`** — wąskie typy + re-raise/log.
- Testy: **pytest**, funkcje bez klas, `respx` do mocków httpx.
- Floor SDK: **`mcp[cli]>=1.28.0`** (wersja z `TokenVerifier`/RS-auth; potwierdzone na 1.28.1).
- Docstringi/komentarze po polsku (jak reszta pakietu).
- Kontrakt BPP (z `dev`): issuer = root `BPP_BASE_URL`; `whoami` = `GET /api/v1/whoami/` → 200 `{id,username,is_staff,is_superuser}` | 401; scope wyłącznie `read`; token opaque; DCR dopuszcza `http://localhost:*`/`http://127.0.0.1:*`.

---

### Task 1: Bump SDK + rozszerzenie Config

**Files:**
- Modify: `pyproject.toml` (dependency floor)
- Modify: `src/bpp_mcp/config.py`
- Test: `tests/test_config.py`

**Interfaces:**
- Produces: `Config` z nowymi polami `transport: str`, `http_host: str`, `http_port: int`, `resource_url: str | None` oraz property `effective_resource_url -> str`. `Config.from_env()` czyta `BPP_MCP_TRANSPORT`, `BPP_MCP_HTTP_HOST`, `BPP_MCP_HTTP_PORT`, `BPP_MCP_RESOURCE_URL`.

- [ ] **Step 1: Podnieś floor SDK w `pyproject.toml`**

Zmień w `[project].dependencies` linię `"mcp[cli]>=1.2.0",` na:

```toml
    "mcp[cli]>=1.28.0",
```

Uruchom: `uv lock` a potem `uv sync`. Oczekiwane: lock zaktualizowany, brak błędów.

- [ ] **Step 2: Napisz failujący test rozszerzonego Config**

W `tests/test_config.py` dopisz:

```python
from dataclasses import replace

from bpp_mcp.config import Config


def test_from_env_transport_defaults(monkeypatch):
    for k in ("BPP_MCP_TRANSPORT", "BPP_MCP_HTTP_HOST",
              "BPP_MCP_HTTP_PORT", "BPP_MCP_RESOURCE_URL"):
        monkeypatch.delenv(k, raising=False)
    cfg = Config.from_env()
    assert cfg.transport == "stdio"
    assert cfg.http_host == "127.0.0.1"
    assert cfg.http_port == 8000
    assert cfg.effective_resource_url == "http://127.0.0.1:8000"


def test_from_env_transport_http(monkeypatch):
    monkeypatch.setenv("BPP_MCP_TRANSPORT", "HTTP")
    monkeypatch.setenv("BPP_MCP_HTTP_PORT", "9123")
    monkeypatch.delenv("BPP_MCP_RESOURCE_URL", raising=False)
    cfg = Config.from_env()
    assert cfg.transport == "http"
    assert cfg.http_port == 9123
    assert cfg.effective_resource_url == "http://127.0.0.1:9123"


def test_resource_url_override(monkeypatch):
    monkeypatch.setenv("BPP_MCP_RESOURCE_URL", "http://127.0.0.1:9000/mcp")
    cfg = Config.from_env()
    assert cfg.effective_resource_url == "http://127.0.0.1:9000/mcp"
```

- [ ] **Step 3: Uruchom test — ma failować**

Run: `uv run pytest tests/test_config.py -q`
Expected: FAIL (`transport` nie istnieje / `AttributeError`).

- [ ] **Step 4: Rozszerz `Config`**

W `src/bpp_mcp/config.py` dodaj pola do dataclass i logikę w `from_env`. Dopisz pola do `class Config` (po istniejących `base_url`, `basic_auth`):

```python
    transport: str = "stdio"
    http_host: str = "127.0.0.1"
    http_port: int = 8000
    resource_url: str | None = None

    @property
    def effective_resource_url(self) -> str:
        """URL zasobu do pola ``resource`` w protected-resource-metadata.
        Domyślnie budowany z hosta i portu HTTP."""
        return self.resource_url or f"http://{self.http_host}:{self.http_port}"
```

W `from_env` (po odczycie `base`/`auth`) dodaj:

```python
        transport = os.environ.get("BPP_MCP_TRANSPORT", "stdio").lower()
        http_host = os.environ.get("BPP_MCP_HTTP_HOST", "127.0.0.1")
        http_port = int(os.environ.get("BPP_MCP_HTTP_PORT", "8000"))
        resource_url = os.environ.get("BPP_MCP_RESOURCE_URL") or None
        return cls(
            base_url=base,
            basic_auth=auth,
            transport=transport,
            http_host=http_host,
            http_port=http_port,
            resource_url=resource_url,
        )
```

(Usuń wcześniejszy `return cls(base_url=base, basic_auth=auth)`.)

- [ ] **Step 5: Uruchom testy — mają przejść**

Run: `uv run pytest tests/test_config.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml uv.lock src/bpp_mcp/config.py tests/test_config.py
git commit -m "feat(config): transport/http/resource + bump mcp>=1.28"
```

---

### Task 2: WhoamiTokenVerifier + current_bearer + positive-cache

**Files:**
- Create: `src/bpp_mcp/auth.py`
- Test: `tests/test_auth.py`

**Interfaces:**
- Consumes: `Config.base_url` (Task 1).
- Produces:
  - `class WhoamiTokenVerifier` implementujący protokół SDK `TokenVerifier`: `async def verify_token(self, token: str) -> AccessToken | None`. Konstruktor: `WhoamiTokenVerifier(base_url: str, *, ttl: float = 30.0)`.
  - `class WhoamiUnavailable(Exception)` — BPP niedostępne (5xx/sieć) → NIE `None`.
  - `def current_bearer() -> str | None` — token bieżącego requestu (wrapper `get_access_token()`).

- [ ] **Step 1: Napisz failujące testy**

Utwórz `tests/test_auth.py`:

```python
import httpx
import pytest
import respx

from bpp_mcp.auth import WhoamiTokenVerifier, WhoamiUnavailable

BASE = "https://bpp.example.test"
WHOAMI = f"{BASE}/api/v1/whoami/"


@pytest.mark.asyncio
@respx.mock
async def test_valid_token_zwraca_accesstoken():
    respx.get(WHOAMI).mock(
        return_value=httpx.Response(
            200, json={"id": 7, "username": "kowalski",
                       "is_staff": True, "is_superuser": False})
    )
    v = WhoamiTokenVerifier(BASE)
    tok = await v.verify_token("OPAQUE")
    assert tok is not None
    assert tok.token == "OPAQUE"
    assert tok.scopes == ["read"]
    assert tok.subject == "7"


@pytest.mark.asyncio
@respx.mock
async def test_invalid_token_zwraca_none():
    respx.get(WHOAMI).mock(return_value=httpx.Response(401))
    v = WhoamiTokenVerifier(BASE)
    assert await v.verify_token("ZLY") is None


@pytest.mark.asyncio
@respx.mock
async def test_bpp_5xx_podnosi_unavailable():
    respx.get(WHOAMI).mock(return_value=httpx.Response(503))
    v = WhoamiTokenVerifier(BASE)
    with pytest.raises(WhoamiUnavailable):
        await v.verify_token("OPAQUE")


@pytest.mark.asyncio
@respx.mock
async def test_siec_padla_podnosi_unavailable():
    respx.get(WHOAMI).mock(side_effect=httpx.ConnectError("down"))
    v = WhoamiTokenVerifier(BASE)
    with pytest.raises(WhoamiUnavailable):
        await v.verify_token("OPAQUE")


@pytest.mark.asyncio
@respx.mock
async def test_positive_cache_jeden_hit_whoami():
    route = respx.get(WHOAMI).mock(
        return_value=httpx.Response(200, json={"id": 1, "username": "a"}))
    v = WhoamiTokenVerifier(BASE, ttl=60.0)
    await v.verify_token("T")
    await v.verify_token("T")
    assert route.call_count == 1
```

- [ ] **Step 2: Uruchom testy — mają failować**

Run: `uv run pytest tests/test_auth.py -q`
Expected: FAIL (`ModuleNotFoundError: bpp_mcp.auth`).

- [ ] **Step 3: Zaimplementuj `auth.py`**

Utwórz `src/bpp_mcp/auth.py`:

```python
"""Warstwa OAuth Resource Server: weryfikacja opaque tokenu BPP przez
``whoami`` oraz akcesor bieżącego tokenu dla passthrough w BppClient.

Token BPP jest OPAQUE (nie JWT) — nie da się go zweryfikować lokalnie
podpisem. Jedyna weryfikacja to zdalne ``GET /api/v1/whoami/``:
200 → ważny (tożsamość), 401/403 → nieważny (``None`` → transportowy 401),
5xx/sieć → :class:`WhoamiUnavailable` (BPP niedostępne, NIE re-auth).
"""

from __future__ import annotations

import time

import httpx
from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.auth.provider import AccessToken


class WhoamiUnavailable(Exception):
    """BPP niedostępne przy weryfikacji tokenu (5xx / błąd sieci).

    Świadomie różne od zwrócenia ``None`` (token nieważny → re-auth):
    tu token mógł być ważny, więc nie wymuszamy zbędnej re-autoryzacji.
    """


class WhoamiTokenVerifier:
    """``TokenVerifier`` (protokół SDK) oparty o endpoint ``whoami`` BPP.

    Positive-cache (``ttl`` s) trzyma wynik pozytywnej weryfikacji per token —
    redukuje +1 request na wywołanie narzędzia i wygładza chwilowe blipy.
    TTL = maksymalne opóźnienie, zanim zrewokowany token przestanie działać.
    """

    def __init__(self, base_url: str, *, ttl: float = 30.0) -> None:
        self._base_url = base_url.rstrip("/")
        self._ttl = ttl
        self._cache: dict[str, tuple[AccessToken, float]] = {}

    async def verify_token(self, token: str) -> AccessToken | None:
        now = time.monotonic()
        cached = self._cache.get(token)
        if cached is not None and cached[1] > now:
            return cached[0]
        url = f"{self._base_url}/api/v1/whoami/"
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
        }
        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(10.0, connect=5.0)
            ) as client:
                resp = await client.get(url, headers=headers)
        except httpx.HTTPError as exc:
            raise WhoamiUnavailable(f"whoami niedostępne: {exc}") from exc
        if resp.status_code in (401, 403):
            return None
        if resp.status_code >= 500:
            raise WhoamiUnavailable(f"whoami zwróciło {resp.status_code}")
        resp.raise_for_status()
        data = resp.json()
        access = AccessToken(
            token=token,
            client_id="bpp-mcp",
            scopes=["read"],
            subject=str(data.get("id")) if data.get("id") is not None else None,
            claims=data,
        )
        self._cache[token] = (access, now + self._ttl)
        return access


def current_bearer() -> str | None:
    """Zwróć surowy token bieżącego requestu (lub ``None`` poza kontekstem
    auth, np. w trybie stdio). Wrapper akcesora SDK ``get_access_token()``."""
    tok = get_access_token()
    return tok.token if tok is not None else None
```

- [ ] **Step 4: Uruchom testy — mają przejść**

Run: `uv run pytest tests/test_auth.py -q`
Expected: PASS (5 passed).

- [ ] **Step 5: Commit**

```bash
git add src/bpp_mcp/auth.py tests/test_auth.py
git commit -m "feat(auth): WhoamiTokenVerifier + current_bearer + positive-cache"
```

---

### Task 3: BppClient — passthrough Bearera (precedencja Bearer > Basic > anon)

**Files:**
- Modify: `src/bpp_mcp/client.py:56-70` (konstruktor) i `src/bpp_mcp/client.py:98-135` (`_request`)
- Test: `tests/test_client_auth.py`

**Interfaces:**
- Consumes: `current_bearer()` (Task 2), `Config.auth_tuple` (istnieje).
- Produces: `BppClient` wysyła per-request `Authorization: Bearer <token>` gdy `current_bearer()` zwróci token; inaczej Basic (gdy `auth_tuple`); inaczej anonimowo.

- [ ] **Step 1: Napisz failujące testy**

Utwórz `tests/test_client_auth.py`:

```python
import httpx
import pytest
import respx

from bpp_mcp import client as client_mod
from bpp_mcp.client import BppClient
from bpp_mcp.config import Config

BASE = "https://bpp.example.test"
PING = f"{BASE}/api/v1/uczelnia/1/"


def _cfg(basic=None):
    return Config(base_url=BASE, basic_auth=basic)


@pytest.mark.asyncio
@respx.mock
async def test_bearer_z_kontekstu_jest_forwardowany(monkeypatch):
    monkeypatch.setattr(client_mod, "current_bearer", lambda: "TESTTOKEN")
    route = respx.get(PING).mock(return_value=httpx.Response(200, json={"ok": 1}))
    async with BppClient(_cfg()) as c:
        await c.get_json("uczelnia/1/")
    assert route.calls.last.request.headers["Authorization"] == "Bearer TESTTOKEN"


@pytest.mark.asyncio
@respx.mock
async def test_brak_bearera_brak_basic_leci_anonimowo(monkeypatch):
    monkeypatch.setattr(client_mod, "current_bearer", lambda: None)
    route = respx.get(PING).mock(return_value=httpx.Response(200, json={"ok": 1}))
    async with BppClient(_cfg()) as c:
        await c.get_json("uczelnia/1/")
    assert "Authorization" not in route.calls.last.request.headers


@pytest.mark.asyncio
@respx.mock
async def test_bearer_wygrywa_z_basic(monkeypatch):
    monkeypatch.setattr(client_mod, "current_bearer", lambda: "BEAR")
    route = respx.get(PING).mock(return_value=httpx.Response(200, json={"ok": 1}))
    async with BppClient(_cfg(basic="u:p")) as c:
        await c.get_json("uczelnia/1/")
    assert route.calls.last.request.headers["Authorization"] == "Bearer BEAR"


@pytest.mark.asyncio
@respx.mock
async def test_basic_gdy_brak_bearera(monkeypatch):
    monkeypatch.setattr(client_mod, "current_bearer", lambda: None)
    route = respx.get(PING).mock(return_value=httpx.Response(200, json={"ok": 1}))
    async with BppClient(_cfg(basic="u:p")) as c:
        await c.get_json("uczelnia/1/")
    # Basic base64("u:p") == "dTpw"
    assert route.calls.last.request.headers["Authorization"] == "Basic dTpw"
```

- [ ] **Step 2: Uruchom testy — mają failować**

Run: `uv run pytest tests/test_client_auth.py -q`
Expected: FAIL (Bearer nie jest forwardowany; `current_bearer` nie istnieje w module).

- [ ] **Step 3: Zmodyfikuj `client.py`**

Dodaj import na górze (po `import httpx`):

```python
from .auth import current_bearer
```

W `__init__` USUŃ `auth=config.auth_tuple,` z konstrukcji `httpx.AsyncClient(...)` i ZAPISZ tuple do pola. Konstrukcja klienta ma być:

```python
        self._auth_tuple = config.auth_tuple
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(10.0, connect=5.0),
            headers={"Accept": "application/json"},
            follow_redirects=True,
        )
```

Dodaj metodę pomocniczą (np. tuż nad `_request`):

```python
    def _auth_kwargs(self) -> dict[str, Any]:
        """Per-request auth: Bearer (OAuth) > Basic (serwisowy) > anonimowo."""
        bearer = current_bearer()
        if bearer:
            return {"headers": {"Authorization": f"Bearer {bearer}"}}
        if self._auth_tuple:
            return {"auth": self._auth_tuple}
        return {}
```

W `_request` zmień wywołanie GET:

```python
                    resp = await self._client.get(full, **self._auth_kwargs())
```

- [ ] **Step 4: Uruchom testy — mają przejść**

Run: `uv run pytest tests/test_client_auth.py -q`
Expected: PASS (4 passed).

- [ ] **Step 5: Regres — cała dotychczasowa suita**

Run: `uv run pytest -q`
Expected: PASS (istniejące testy klienta/narzędzi bez zmian).

- [ ] **Step 6: Commit**

```bash
git add src/bpp_mcp/client.py tests/test_client_auth.py
git commit -m "feat(client): passthrough Bearera (Bearer > Basic > anon)"
```

---

### Task 4: server.py — fabryka `build_mcp` + transport HTTP + wiring auth + CLI

**Files:**
- Modify: `src/bpp_mcp/server.py` (dekoratory → funkcje + `_register` + `build_mcp` + `main`)
- Test: `tests/test_http_auth.py`

**Interfaces:**
- Consumes: `WhoamiTokenVerifier` (Task 2), rozszerzony `Config` (Task 1).
- Produces:
  - `def build_mcp(config: Config) -> FastMCP` — buduje serwer; w trybie `http` dokłada `token_verifier` + `AuthSettings` + host/port.
  - `def _register(mcp: FastMCP) -> None` — rejestruje 8 narzędzi + prompt.
  - `mcp: FastMCP` (modułowy, z `Config.from_env()`) — dla stdio i istniejących testów.
  - `main()` z flagami `--http`, `--port`, `--host`.

- [ ] **Step 1: Napisz failujące testy HTTP/PRM**

Utwórz `tests/test_http_auth.py`:

```python
import httpx
import pytest

from bpp_mcp.config import Config
from bpp_mcp.server import _auth_kwargs, build_mcp

BASE = "https://bpp.example.test"


def _http_cfg():
    return Config(base_url=BASE, transport="http",
                  http_host="127.0.0.1", http_port=8055)


def test_auth_kwargs_stdio_puste():
    assert _auth_kwargs(Config(base_url=BASE)) == {}


def test_auth_kwargs_http_ma_verifier_i_auth():
    kw = _auth_kwargs(_http_cfg())
    assert "token_verifier" in kw
    assert "auth" in kw
    assert kw["host"] == "127.0.0.1"
    assert kw["port"] == 8055


@pytest.mark.asyncio
async def test_protected_resource_metadata():
    app = build_mcp(_http_cfg()).streamable_http_app()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://testserver"
    ) as c:
        resp = await c.get("/.well-known/oauth-protected-resource")
    assert resp.status_code == 200
    body = resp.json()
    assert BASE in body["authorization_servers"]
    assert body["resource"].startswith("http://127.0.0.1:8055")


@pytest.mark.asyncio
async def test_brak_tokenu_daje_401_i_www_authenticate():
    app = build_mcp(_http_cfg()).streamable_http_app()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://testserver"
    ) as c:
        resp = await c.post("/mcp", json={"jsonrpc": "2.0", "method": "ping",
                                          "id": 1})
    assert resp.status_code == 401
    assert "WWW-Authenticate" in resp.headers
```

- [ ] **Step 2: Uruchom testy — mają failować**

Run: `uv run pytest tests/test_http_auth.py -q`
Expected: FAIL (`_auth_kwargs`/`build_mcp` nie istnieją).

- [ ] **Step 3: Zrefaktoryzuj `server.py`**

Zmień tak, by narzędzia były zwykłymi funkcjami modułowymi (BEZ dekoratora `@mcp.tool()`), a rejestracja szła przez `_register`. Konkretnie:

1. Usuń dekoratory `@mcp.tool()` i `@mcp.prompt(...)` znad wszystkich 8 funkcji narzędzi i funkcji `zloz_zapytanie_djangoql` (same funkcje i `PROMPT_ZLOZ_ZAPYTANIE` zostają nietknięte — pozostają importowalne).
2. Usuń linię `mcp = FastMCP("bpp-mcp", lifespan=lifespan)` sprzed narzędzi.
3. Dodaj importy na górze:

```python
import argparse
from dataclasses import replace

from mcp.server.auth.settings import AuthSettings

from .auth import WhoamiTokenVerifier
```

4. Na końcu pliku (po definicjach funkcji i `PROMPT_ZLOZ_ZAPYTANIE`) dodaj fabrykę, rejestrację, modułowy `mcp` i nowy `main`:

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
    """Argumenty auth do konstruktora FastMCP. Puste w trybie stdio; w trybie
    http dokłada token_verifier + AuthSettings (RS) + host/port."""
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
    """Zbuduj serwer FastMCP dla danej konfiguracji (stdio lub http+OAuth)."""
    mcp = FastMCP("bpp-mcp", lifespan=lifespan, **_auth_kwargs(config))
    _register(mcp)
    return mcp


# Modułowy serwer (env-driven) — używany przez stdio-entry i istniejące testy.
mcp = build_mcp(Config.from_env())


def main() -> None:
    """Punkt wejścia ``bpp-mcp``: bez flag → stdio (anonimowy/Basic); ``--http``
    → Streamable HTTP + OAuth (Resource Server)."""
    parser = argparse.ArgumentParser(prog="bpp-mcp")
    parser.add_argument("--http", action="store_true",
                        help="Streamable HTTP + OAuth (Resource Server).")
    parser.add_argument("--host", default=None, help="Host HTTP (domyślnie 127.0.0.1).")
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
    server = build_mcp(config)
    if config.transport == "http":
        server.run(transport="streamable-http")
    else:
        server.run()
```

Uwaga: `_client(ctx)` zostaje modułowe (używane przez narzędzia). `if __name__ == "__main__": main()` zostaje na końcu.

- [ ] **Step 4: Uruchom nowe testy — mają przejść**

Run: `uv run pytest tests/test_http_auth.py -q`
Expected: PASS (4 passed). Jeśli `test_brak_tokenu...` zwróci inny kod niż 401 — sprawdź, czy `token_verifier` + `auth` trafiły do FastMCP (są w `_auth_kwargs`).

- [ ] **Step 5: Regres — cała suita (w tym istniejące testy `mcp`)**

Run: `uv run pytest -q`
Expected: PASS (istniejące `tests/test_server.py`, `tests/test_djangoql_schema.py` dalej zielone — modułowy `mcp` i funkcje/prompt nietknięte).

- [ ] **Step 6: Ręczny smoke stdio (bez regresu zachowania)**

Run: `printf '' | BPP_MCP_TRANSPORT=stdio uv run bpp-mcp --help`
Expected: pomoc argparse (flaga `--http`), brak wywołania sieci.

- [ ] **Step 7: Commit**

```bash
git add src/bpp_mcp/server.py tests/test_http_auth.py
git commit -m "feat(server): build_mcp factory + Streamable HTTP + OAuth wiring + CLI"
```

---

### Task 5: Dokumentacja uruchomienia (README)

**Files:**
- Modify: `README.md`

**Interfaces:**
- Consumes: CLI `--http`/`--port` i zmienne `BPP_*` (Task 1, 4).

- [ ] **Step 1: Dopisz sekcję „Tryb OAuth (HTTP)" do README**

W `README.md`, w sekcji „Instalacja i uruchomienie", dodaj podsekcję:

````markdown
### Tryb OAuth (HTTP, per-user)

Domyślnie `bpp-mcp` działa po **stdio** i anonimowo (dane publiczne). Aby
działać **z uprawnieniami zalogowanego użytkownika BPP** (OAuth 2.1), uruchom
serwer jako lokalny Resource Server po HTTP:

```bash
BPP_BASE_URL=https://bpp.umlub.pl uv run bpp-mcp --http --port 8000
```

Klient MCP (Claude) sam przeprowadza logowanie: wykrywa serwer autoryzacji BPP
przez `/.well-known/oauth-protected-resource`, rejestruje się dynamicznie
(DCR), otwiera przeglądarkę na logowanie BPP i ekran zgody (scope `read`), po
czym wywołuje narzędzia z tokenem `Bearer`. `bpp-mcp` weryfikuje token przez
`GET /api/v1/whoami/` i forwarduje go do `/api/v1/`. Zapis jest zablokowany
serwerowo (read-only).

Zmienne środowiskowe: `BPP_BASE_URL` (instancja BPP = API i issuer OAuth),
`BPP_MCP_TRANSPORT` (`stdio`|`http`), `BPP_MCP_HTTP_HOST` (domyślnie
`127.0.0.1`), `BPP_MCP_HTTP_PORT`, `BPP_MCP_RESOURCE_URL` (domyślnie
`http://<host>:<port>`).
````

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "docs(readme): tryb OAuth (HTTP) — jak uruchomić i jak działa"
```

---

## Kolejność i zależności

Task 1 → 2 → 3 → 4 → 5. Task 3 importuje `auth.current_bearer` (Task 2); Task 4 importuje `WhoamiTokenVerifier` (Task 2) i rozszerzony `Config` (Task 1). Każdy task kończy się zielonymi testami i commitem.

## Po wdrożeniu

- Ręczny smoke end-to-end wobec żywej instancji (opcjonalny, poza CI): uruchom `bpp-mcp --http`, podłącz klienta MCP obsługującego OAuth, przejdź pełny dance i wywołaj `whoami`-zależne narzędzie. Zweryfikuj 403 na próbie zapisu.
- Otwórz PR z gałęzi `feat-oauth-resource-server` do `main`.
