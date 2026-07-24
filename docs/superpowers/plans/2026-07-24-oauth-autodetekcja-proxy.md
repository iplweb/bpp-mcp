# Autodetekcja #21 + self-healing proxy metadanych OAuth — plan implementacji

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** bpp-mcp w trybie `--http` sam wykrywa przy starcie, czy instancja BPP ma wdrożony nginx-fix #21, i albo kieruje klienta wprost do BPP (PASS-THROUGH), albo serwuje własne metadane RFC 8414 wskazujące na `/o/*` (PROXY) — dzięki czemu „Authorize" działa też na instancjach bez #21.

**Architecture:** Jeden probe HTTP przy starcie wybiera tryb na całe życie procesu. PROXY jest bezpiecznym stanem domyślnym (endpointy `/o/*` istnieją na każdej instancji BPP); PASS-THROUGH włącza się tylko po potwierdzeniu czystych metadanych. Logika reużywa istniejącego `oauth_client.discover()`/`_konwencjonalne()`. Wpięcie przez parametr `mode` w `build_mcp`/`_auth_kwargs` oraz warunkową `custom_route` FastMCP.

**Tech Stack:** Python 3, `httpx` (klient + `MockTransport` w testach), `mcp.server.fastmcp.FastMCP`, `starlette` (JSONResponse w custom_route), `pytest` + `pytest-asyncio`.

## Global Constraints

- Python: zgodnie z istniejącym `pyproject.toml` (bez zmian floora).
- Zależności: tylko już obecne (`httpx`, `mcp`, `starlette` tranzytywnie z `mcp`). Nie dodajemy nowych.
- `BPP_BASE_URL` pozostaje WYMAGANY, bez wartości domyślnej (istniejący kontrakt).
- Sieć w kodzie zawsze przez wstrzykiwalny `httpx.Client` — testy bez realnej sieci.
- Domyślny tryb przy niepewności = PROXY. Tylko 200 + obiekt JSON z polami `authorization_endpoint` i `token_endpoint` daje PASS-THROUGH.
- Komunikaty i docstringi po polsku (konwencja repo).
- Commity: jeden na task, po zielonych testach.

---

## Task 0: Spike empiryczny (bramka decyzyjna — RĘCZNY)

Cała wartość funkcji stoi na założeniu, że klient MCP (Claude Code) akceptuje metadane AS z `issuer` = URL bpp-mcp i endpointami na innym origin (BPP). Ten task potwierdza to jednym klikiem, ZANIM napiszemy kod produkcyjny.

**Files:** brak zmian commitowanych (kod tymczasowy, wyrzucany po spike).

- [ ] **Krok 1: Tymczasowa gałąź robocza spike'a**

```bash
cd ~/Programowanie/bpp-mcp
git checkout -b spike-oauth-proxy-throwaway
```

- [ ] **Krok 2: Doklej tymczasową trasę AS-metadata do serwera HTTP**

W `src/bpp_mcp/server.py`, w `build_mcp`, tuż przed `return mcp`, wklej tymczasowo (do usunięcia):

```python
    if config.transport == "http":
        from pydantic import AnyHttpUrl
        from starlette.responses import JSONResponse

        # Znormalizowany issuer — MUSI być bajt w bajt jak w PRM (patrz niżej),
        # inaczej spike padnie na rozjeździe trailing-slash, nie na wadzie projektu.
        _iss = str(AnyHttpUrl(config.effective_resource_url.removesuffix("/mcp")))

        @mcp.custom_route("/.well-known/oauth-authorization-server", methods=["GET"])
        async def _spike_as(request):
            base = config.base_url.rstrip("/")
            return JSONResponse(
                {
                    "issuer": _iss,
                    "authorization_endpoint": f"{base}/o/authorize/",
                    "token_endpoint": f"{base}/o/token/",
                    "registration_endpoint": f"{base}/o/register/",
                    "code_challenge_methods_supported": ["S256"],
                    "token_endpoint_auth_methods_supported": ["none"],
                }
            )
```

Uwaga: `effective_resource_url` (dziś `http://127.0.0.1:8000/mcp`) trafia do PRM jako `resource`, ale `issuer` w PRM to `issuer_url` z `AuthSettings` = `base_url` (BPP). Dla spike'a chcemy, by klient poszedł po AS-metadata do NAS, więc dodatkowo ustaw tymczasowo w `_auth_kwargs` `issuer_url=config.effective_resource_url.removesuffix("/mcp")` zamiast `config.base_url` (pydantic znormalizuje go tak samo jak `_iss` powyżej — dlatego oba używają tej samej wartości bazowej). To ręczna, jednorazowa podmiana na czas spike'a.

- [ ] **Krok 3: Uruchom serwer HTTP przeciw NIEZMIENIONEJ instancji (403 na discovery)**

```bash
BPP_BASE_URL=https://publikacje.up.lublin.pl uv run bpp-mcp --http --port 8765
```

- [ ] **Krok 4: Podłącz jako connector HTTP i kliknij Authorize**

```bash
claude mcp add --transport http bpp-spike http://127.0.0.1:8765/mcp
```
W kliencie: `/mcp` → przy `bpp-spike` powinno pojawić się „Authorize". Kliknij, przejdź flow w przeglądarce.

- [ ] **Krok 5: BRAMKA — oceń wynik**

Sukces = discovery → DCR (`/o/register/`) → authorize → token → whoami przechodzi i narzędzia BPP działają jako zalogowany.
- **Jeśli sukces:** usuń tymczasowy kod, `git checkout main-owa-gałąź`, skasuj `spike-oauth-proxy-throwaway`, kontynuuj Task 1.
- **Jeśli porażka:** ZATRZYMAJ plan. Zanotuj, na którym kroku padło (np. klient odrzucił split issuer/endpoint), wróć do brainstormingu. Koszt: ~15 min zamiast pełnej implementacji na fałszywym założeniu.

- [ ] **Krok 6: Sprzątanie po spike'u**

```bash
claude mcp remove bpp-spike
git checkout feat-oauth-autodetekcja-proxy
git branch -D spike-oauth-proxy-throwaway
```

---

## Task 1: `AuthMode` + `probe_instance()`

**Files:**
- Modify: `src/bpp_mcp/oauth_client.py` (dodanie enuma i funkcji, obok `discover()`)
- Test: `tests/test_probe.py` (nowy)

**Interfaces:**
- Produces: `AuthMode` (enum: `PASSTHROUGH`, `PROXY`); `probe_instance(base_url: str, *, client: httpx.Client | None = None) -> AuthMode`

- [ ] **Step 1: Napisz failing test**

Utwórz `tests/test_probe.py`:

```python
import httpx

from bpp_mcp.oauth_client import AuthMode, probe_instance


def _client(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_passthrough_gdy_poprawne_metadane():
    def h(_req):
        return httpx.Response(
            200, json={"authorization_endpoint": "a", "token_endpoint": "t"}
        )

    assert probe_instance("https://bpp.test", client=_client(h)) is AuthMode.PASSTHROUGH


def test_proxy_gdy_403():
    def h(_req):
        return httpx.Response(403, text="<html>forbidden</html>")

    assert probe_instance("https://bpp.test", client=_client(h)) is AuthMode.PROXY


def test_proxy_gdy_html_200():
    def h(_req):
        return httpx.Response(200, text="<html>nie json</html>")

    assert probe_instance("https://bpp.test", client=_client(h)) is AuthMode.PROXY


def test_proxy_gdy_brak_wymaganych_pol():
    def h(_req):
        return httpx.Response(200, json={"issuer": "x"})

    assert probe_instance("https://bpp.test", client=_client(h)) is AuthMode.PROXY


def test_proxy_gdy_timeout():
    def h(_req):
        raise httpx.ConnectTimeout("wolno")

    assert probe_instance("https://bpp.test", client=_client(h)) is AuthMode.PROXY


def test_proxy_gdy_5xx():
    def h(_req):
        return httpx.Response(502, text="bad gateway")

    assert probe_instance("https://bpp.test", client=_client(h)) is AuthMode.PROXY
```

- [ ] **Step 2: Uruchom test — ma paść**

Run: `uv run pytest tests/test_probe.py -v`
Expected: FAIL — `ImportError: cannot import name 'AuthMode'`

- [ ] **Step 3: Minimalna implementacja**

W `src/bpp_mcp/oauth_client.py` dodaj `import enum` na górze (przy innych importach) oraz poniżej definicji `Metadata`:

```python
class AuthMode(enum.Enum):
    """Tryb, w jakim serwer HTTP wystawia discovery OAuth klientowi MCP."""

    PASSTHROUGH = "passthrough"  # instancja z #21 — klient idzie wprost do BPP
    PROXY = "proxy"  # instancja bez #21 — bpp-mcp serwuje własne metadane AS


def probe_instance(
    base_url: str, *, client: httpx.Client | None = None
) -> AuthMode:
    """Wykryj, czy instancja BPP wystawia poprawne metadane RFC 8414.

    PASS-THROUGH tylko przy potwierdzonym 200 + obiekt JSON z polami
    ``authorization_endpoint`` oraz ``token_endpoint`` (warunek identyczny z
    sukcesem :func:`discover`). Wszystko inne — 403 od nginxa blokującego
    ``/.well-known/``, HTML zamiast JSON, 5xx, timeout, brak pól — daje PROXY.
    PROXY jest bezpiecznym stanem domyślnym: endpointy ``/o/*`` istnieją na
    każdej instancji BPP niezależnie od wdrożenia #21.
    """
    url = f"{base_url.rstrip('/')}/.well-known/oauth-authorization-server"
    cli, owns = _client_ctx(client)
    try:
        resp = cli.get(url)
        if resp.status_code != 200:
            return AuthMode.PROXY
        data = resp.json()
        if not isinstance(data, dict):
            return AuthMode.PROXY
        if "authorization_endpoint" not in data or "token_endpoint" not in data:
            return AuthMode.PROXY
        return AuthMode.PASSTHROUGH
    except (httpx.HTTPError, ValueError):
        return AuthMode.PROXY
    finally:
        if owns:
            cli.close()
```

- [ ] **Step 4: Uruchom test — ma przejść**

Run: `uv run pytest tests/test_probe.py -v`
Expected: PASS (6 passed)

- [ ] **Step 5: Commit**

```bash
git add src/bpp_mcp/oauth_client.py tests/test_probe.py
git commit -m "feat(oauth): probe_instance — wykrywa czy #21 wdrozony (PASSTHROUGH/PROXY)"
```

---

## Task 2: Rozszerzenie `_konwencjonalne` o revoke + builder metadanych AS

**Files:**
- Modify: `src/bpp_mcp/oauth_client.py` (`Metadata`, `_konwencjonalne`, nowa `authorization_server_metadata`)
- Test: `tests/test_metadata_proxy.py` (nowy)

**Interfaces:**
- Consumes: `_konwencjonalne(base_url) -> Metadata` (istniejąca)
- Produces: `Metadata.revocation_endpoint: str | None`; `authorization_server_metadata(base_url: str, issuer: str) -> dict`

- [ ] **Step 1: Napisz failing test**

Utwórz `tests/test_metadata_proxy.py`:

```python
from bpp_mcp.oauth_client import _konwencjonalne, authorization_server_metadata


def test_konwencjonalne_zawiera_revoke():
    m = _konwencjonalne("https://bpp.test/")
    assert m.revocation_endpoint == "https://bpp.test/o/revoke_token/"


def test_metadata_issuer_self_endpointy_bpp():
    doc = authorization_server_metadata("https://bpp.test", "http://127.0.0.1:8000")
    # issuer znormalizowany przez AnyHttpUrl DOKŁADNIE jak w PRM (AuthSettings),
    # by RFC 8414 §3.3 (issuer == adres pobrania) trzymał się bajt w bajt.
    assert doc["issuer"] == "http://127.0.0.1:8000/"
    assert doc["authorization_endpoint"] == "https://bpp.test/o/authorize/"
    assert doc["token_endpoint"] == "https://bpp.test/o/token/"
    assert doc["registration_endpoint"] == "https://bpp.test/o/register/"
    assert doc["revocation_endpoint"] == "https://bpp.test/o/revoke_token/"
    assert doc["code_challenge_methods_supported"] == ["S256"]
    assert doc["token_endpoint_auth_methods_supported"] == ["none"]


def test_metadata_issuer_ze_sciezka_reverse_proxy():
    # Za reverse-proxy issuer ma ścieżkę — AnyHttpUrl NIE dokłada ukośnika.
    doc = authorization_server_metadata("https://bpp.test", "https://mcp.example/bpp")
    assert doc["issuer"] == "https://mcp.example/bpp"
```

- [ ] **Step 2: Uruchom test — ma paść**

Run: `uv run pytest tests/test_metadata_proxy.py -v`
Expected: FAIL — `ImportError: cannot import name 'authorization_server_metadata'`

- [ ] **Step 3: Minimalna implementacja**

W `src/bpp_mcp/oauth_client.py` dodaj import na górze (przy innych importach; `pydantic` jest tranzytywną zależnością `mcp`, nie dokładamy nowej):

```python
from pydantic import AnyHttpUrl
```

Rozszerz `Metadata` o pole `revocation_endpoint`:

```python
@dataclass
class Metadata:
    authorization_endpoint: str
    token_endpoint: str
    registration_endpoint: str | None
    revocation_endpoint: str | None = None
```

Rozszerz `_konwencjonalne` o revoke (wspólne źródło ścieżek `/o/*`):

```python
def _konwencjonalne(base_url: str) -> Metadata:
    """Ścieżki, pod którymi BPP montuje serwer autoryzacji (``oauth_mcp/urls.py``).

    Używane jako fallback, gdy metadanych RFC 8414 nie da się odczytać, oraz
    jako źródło endpointów dla trybu PROXY (:func:`authorization_server_metadata`).
    """
    base = base_url.rstrip("/")
    return Metadata(
        authorization_endpoint=f"{base}/o/authorize/",
        token_endpoint=f"{base}/o/token/",
        registration_endpoint=f"{base}/o/register/",
        revocation_endpoint=f"{base}/o/revoke_token/",
    )
```

Dodaj builder (poniżej `_konwencjonalne`):

```python
def authorization_server_metadata(base_url: str, issuer: str) -> dict:
    """Dokument RFC 8414 dla trybu PROXY: ``issuer`` = URL bpp-mcp (adres, spod
    którego klient pobiera ten dokument), endpointy → ``BPP/o/*``.

    Kopiuje kontrakt z ``bpp/src/oauth_mcp/views_metadata.py``, by PROXY i
    PASS-THROUGH dawały klientowi identyczny obraz serwera autoryzacji.
    """
    m = _konwencjonalne(base_url)
    # Normalizacja przez AnyHttpUrl daje formę IDENTYCZNĄ z tą, którą
    # AuthSettings wystawia w PRM (authorization_servers) — inaczej trailing
    # slash rozjechałby issuer między PRM a dokumentem AS (RFC 8414 §3.3).
    return {
        "issuer": str(AnyHttpUrl(issuer)),
        "authorization_endpoint": m.authorization_endpoint,
        "token_endpoint": m.token_endpoint,
        "registration_endpoint": m.registration_endpoint,
        "revocation_endpoint": m.revocation_endpoint,
        "scopes_supported": ["read"],
        "response_types_supported": ["code"],
        "grant_types_supported": ["authorization_code", "refresh_token"],
        "code_challenge_methods_supported": ["S256"],
        "token_endpoint_auth_methods_supported": ["none"],
    }
```

- [ ] **Step 4: Uruchom test — ma przejść**

Run: `uv run pytest tests/test_metadata_proxy.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Regresja — istniejące testy oauth_client dalej zielone**

Run: `uv run pytest tests/test_oauth_client.py tests/test_oauth_login.py -q`
Expected: PASS (bez zmian — `revocation_endpoint` ma default `None`, `discover()` niezmieniony)

- [ ] **Step 6: Commit**

```bash
git add src/bpp_mcp/oauth_client.py tests/test_metadata_proxy.py
git commit -m "feat(oauth): builder metadanych AS dla PROXY + revoke w _konwencjonalne"
```

---

## Task 3: Config — `effective_issuer_url` + `BPP_MCP_ISSUER_URL`

**Files:**
- Modify: `src/bpp_mcp/config.py` (pole `issuer_url`, parsowanie env, property `effective_issuer_url`)
- Test: `tests/test_config.py` (dopisanie)

**Interfaces:**
- Consumes: `Config.effective_resource_url` (istniejąca property)
- Produces: `Config.issuer_url: str | None`; `Config.effective_issuer_url -> str`

- [ ] **Step 1: Napisz failing test**

Dopisz do `tests/test_config.py`:

```python
def test_effective_issuer_url_z_resource_bez_mcp():
    c = Config(
        base_url="https://bpp.test",
        transport="http",
        http_host="127.0.0.1",
        http_port=8000,
    )
    assert c.effective_issuer_url == "http://127.0.0.1:8000"


def test_effective_issuer_url_override():
    c = Config(base_url="https://bpp.test", issuer_url="https://mcp.example")
    assert c.effective_issuer_url == "https://mcp.example"
```

- [ ] **Step 2: Uruchom test — ma paść**

Run: `uv run pytest tests/test_config.py -k issuer -v`
Expected: FAIL — `TypeError: __init__() got an unexpected keyword argument 'issuer_url'`

- [ ] **Step 3: Minimalna implementacja**

W `src/bpp_mcp/config.py`, w dataclass `Config`, dodaj pole po `resource_url`:

```python
    resource_url: str | None = None
    issuer_url: str | None = None
```

W `from_env`, dopisz do wywołania `cls(...)`:

```python
            resource_url=os.environ.get("BPP_MCP_RESOURCE_URL") or None,
            issuer_url=os.environ.get("BPP_MCP_ISSUER_URL") or None,
```

Dodaj property poniżej `effective_resource_url`:

```python
    @property
    def effective_issuer_url(self) -> str:
        """URL issuera dla trybu PROXY: pole ``issuer`` w metadanych AS musi
        równać się adresowi, spod którego klient pobiera well-known bpp-mcp.
        Domyślnie ``effective_resource_url`` bez sufiksu ``/mcp``; nadpisywalny
        przez ``BPP_MCP_ISSUER_URL`` (wdrożenia za reverse-proxy)."""
        if self.issuer_url:
            return self.issuer_url
        return self.effective_resource_url.removesuffix("/mcp")
```

Zaktualizuj docstring `from_env` — dopisz linię o `BPP_MCP_ISSUER_URL` obok `BPP_MCP_RESOURCE_URL`.

- [ ] **Step 4: Uruchom test — ma przejść**

Run: `uv run pytest tests/test_config.py -v`
Expected: PASS (wszystkie, w tym dwa nowe)

- [ ] **Step 5: Commit**

```bash
git add src/bpp_mcp/config.py tests/test_config.py
git commit -m "feat(config): effective_issuer_url + BPP_MCP_ISSUER_URL (dla PROXY)"
```

---

## Task 4: Wpięcie w serwer — probe przy starcie, tryb w `build_mcp`, trasa AS w PROXY

**Files:**
- Modify: `src/bpp_mcp/server.py` (`_auth_kwargs`, `build_mcp`, nowa `_register_as_metadata_route`, `main`)
- Test: `tests/test_http_auth.py` (dopisanie 3 testów integracyjnych)

**Interfaces:**
- Consumes: `oauth_client.AuthMode`, `oauth_client.probe_instance`, `oauth_client.authorization_server_metadata`, `Config.effective_issuer_url`
- Produces: `_auth_kwargs(config, mode=AuthMode.PASSTHROUGH)`; `build_mcp(config, mode=AuthMode.PASSTHROUGH)`

- [ ] **Step 1: Napisz failing testy integracyjne**

Dopisz do `tests/test_http_auth.py`:

```python
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
    assert body["issuer"] == "http://127.0.0.1:8055/"
    assert body["authorization_endpoint"] == f"{BASE}/o/authorize/"
    assert body["token_endpoint"] == f"{BASE}/o/token/"


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
    # PRM i dokument AS muszą wskazywać ten sam issuer (z ukośnikiem po norm.).
    assert "http://127.0.0.1:8055/" in resp.json()["authorization_servers"]


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
```

- [ ] **Step 2: Uruchom testy — mają paść**

Run: `uv run pytest tests/test_http_auth.py -k "proxy or passthrough" -v`
Expected: FAIL — `build_mcp() takes 1 positional argument but 2 were given`

- [ ] **Step 3: Minimalna implementacja — `_auth_kwargs` z trybem**

W `src/bpp_mcp/server.py` zmień sygnaturę i logikę issuera:

```python
def _auth_kwargs(
    config: Config,
    mode: oauth_client.AuthMode = oauth_client.AuthMode.PASSTHROUGH,
) -> dict[str, Any]:
    """Argumenty auth do FastMCP: puste w stdio; w http token_verifier +
    AuthSettings (RS) + host/port. W PROXY issuer wskazuje na sam bpp-mcp
    (klient pobierze od nas metadane AS), w PASS-THROUGH — na BPP."""
    if config.transport != "http":
        return {}
    issuer = (
        config.effective_issuer_url
        if mode is oauth_client.AuthMode.PROXY
        else config.base_url
    )
    return {
        "token_verifier": WhoamiTokenVerifier(config.base_url),
        "auth": AuthSettings(
            issuer_url=issuer,
            resource_server_url=config.effective_resource_url,
            required_scopes=["read"],
        ),
        "host": config.http_host,
        "port": config.http_port,
    }
```

- [ ] **Step 4: Implementacja — `build_mcp` z trybem + trasa AS**

Zmień sygnaturę `build_mcp` i dodaj rejestrację trasy w PROXY:

```python
def build_mcp(
    config: Config,
    mode: oauth_client.AuthMode = oauth_client.AuthMode.PASSTHROUGH,
) -> FastMCP:
    """Zbuduj serwer FastMCP. Lifespan zakłada BppClient związany z TYM config
    (W2 — nie z env), więc verifier i klient używają tej samej instancji BPP.
    W trybie PROXY (HTTP) dokłada trasę ``/.well-known/oauth-authorization-server``."""

    @asynccontextmanager
    async def lifespan(_server: FastMCP) -> AsyncIterator[KontekstApp]:
        client = BppClient(config)
        provider = (
            TokenProvider(config.base_url) if config.transport != "http" else None
        )
        try:
            yield KontekstApp(client=client, bearer_provider=provider)
        finally:
            await client.aclose()

    mcp = FastMCP("bpp-mcp", lifespan=lifespan, **_auth_kwargs(config, mode))
    _register(mcp)
    if config.transport == "http" and mode is oauth_client.AuthMode.PROXY:
        _register_as_metadata_route(mcp, config)
    return mcp


def _register_as_metadata_route(mcp: FastMCP, config: Config) -> None:
    """PROXY: wystaw metadane serwera autoryzacji (RFC 8414) pod adresem
    bpp-mcp, wskazując endpointy na ``BPP/o/*``. Dla instancji bez #21, gdzie
    ``BPP/.well-known/`` oddaje 403."""
    from starlette.requests import Request
    from starlette.responses import JSONResponse

    @mcp.custom_route("/.well-known/oauth-authorization-server", methods=["GET"])
    async def _as_metadata(_request: Request) -> JSONResponse:
        return JSONResponse(
            oauth_client.authorization_server_metadata(
                config.base_url, config.effective_issuer_url
            )
        )
```

- [ ] **Step 5: Uruchom testy integracyjne — mają przejść**

Run: `uv run pytest tests/test_http_auth.py -v`
Expected: PASS (istniejące 6 + nowe 3 = 9)

- [ ] **Step 6: Implementacja — probe przy starcie w `main()`**

W `src/bpp_mcp/server.py`, w `main()`, zastąp blok budujący i uruchamiający serwer:

```python
    if args.http:
        config = replace(
            config,
            transport="http",
            http_host=args.host or config.http_host,
            http_port=args.port or config.http_port,
        )
    if config.transport == "http":
        mode = oauth_client.probe_instance(config.base_url)
        gotowa = mode is oauth_client.AuthMode.PASSTHROUGH
        print(
            f"bpp-mcp: discovery OAuth = {mode.value} "
            f"(instancja {'wystawia' if gotowa else 'NIE wystawia'} "
            f".well-known — {'#21 wdrożony' if gotowa else 'proxy przez bpp-mcp'})",
            file=sys.stderr,
        )
        build_mcp(config, mode).run(transport="streamable-http")
    else:
        mcp.run()
```

- [ ] **Step 7: Pełna regresja**

Run: `uv run pytest -q`
Expected: PASS (wszystkie — 157 poprzednich + nowe)

- [ ] **Step 8: Smoke na żywo — PROXY wybrany przeciw niezmienionej instancji**

```bash
BPP_BASE_URL=https://publikacje.up.lublin.pl uv run bpp-mcp --http --port 8766 &
sleep 3
curl -s http://127.0.0.1:8766/.well-known/oauth-authorization-server | python3 -m json.tool
curl -s http://127.0.0.1:8766/.well-known/oauth-protected-resource/mcp | python3 -m json.tool
kill %1
```
Expected: pierwszy `curl` zwraca dokument z `issuer` = `http://127.0.0.1:8766/` i endpointami `.../o/*`; drugi ma `authorization_servers` = `["http://127.0.0.1:8766/"]` (ten sam issuer, z ukośnikiem). Log startu mówi `discovery OAuth = proxy`.

- [ ] **Step 9: Commit**

```bash
git add src/bpp_mcp/server.py tests/test_http_auth.py
git commit -m "feat(server): probe przy starcie + tryb PROXY/PASSTHROUGH w build_mcp"
```

---

## Task 5: Dokumentacja — nowy tryb i zmienna środowiskowa

**Files:**
- Modify: `docs/uwierzytelnianie.md` (sekcja o trybie HTTP / Authorize)
- Modify: `docs/konfiguracja.md` (opis `BPP_MCP_ISSUER_URL`)

**Interfaces:** brak kodu.

- [ ] **Step 1: Sprawdź, co dokumentacja mówi dziś**

Run: `grep -n "BPP_MCP_RESOURCE_URL\|--http\|Authorize\|well-known" docs/uwierzytelnianie.md docs/konfiguracja.md`
Cel: znaleźć istniejący styl i miejsce na dopiskę (dopasuj się do konwencji plików, nie narzucaj nowej struktury).

- [ ] **Step 2: Dopisz opis trybu HTTP i autodetekcji**

W `docs/uwierzytelnianie.md` dodaj akapit: tryb `--http` daje przycisk „Authorize" w kliencie; bpp-mcp przy starcie sam wykrywa, czy instancja BPP wystawia `/.well-known/oauth-authorization-server` (403 od nginxa bez fixu → bpp-mcp serwuje metadane sam, PROXY; poprawne metadane → PASS-THROUGH). Log startu wypisuje wybrany tryb.

W `docs/konfiguracja.md` dodaj wiersz `BPP_MCP_ISSUER_URL` obok `BPP_MCP_RESOURCE_URL`: opcjonalne nadpisanie URL-a issuera dla trybu PROXY za reverse-proxy; domyślnie wyprowadzany z resource-url bez `/mcp`.

- [ ] **Step 3: Commit**

```bash
git add docs/uwierzytelnianie.md docs/konfiguracja.md
git commit -m "docs: tryb HTTP/Authorize, autodetekcja #21 i BPP_MCP_ISSUER_URL"
```

---

## Zależności między taskami

- Task 0 (spike) → bramka; przy porażce reszta nie startuje.
- Task 1, 2, 3 są niezależne (można równolegle), ale wszystkie są konsumowane przez Task 4.
- Task 4 konsumuje 1+2+3.
- Task 5 (docs) po Task 4.
