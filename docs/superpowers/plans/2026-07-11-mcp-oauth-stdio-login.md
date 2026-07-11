# OAuth 2.1 stdio self-login (Droga A) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Umożliwić logowanie użytkownika do BPP przez `bpp-mcp` w trybie stdio (jednorazowe `bpp-mcp login` → przeglądarka → token w cache → cichy forward Bearera do `/api/v1/`).

**Architecture:** `bpp-mcp` staje się public OAuth 2.1 clientem (native-app flow, RFC 8252, loopback + PKCE). Nowe moduły: `token_store` (trwałość, chmod 600), `oauth_client` (discover/DCR/login/refresh), `login_state.TokenProvider` (async dostarczanie bearera z refreshem). Wpięcie w istniejącą ścieżkę ContextVar→`BppClient`. Zero zmian po stronie BPP (AS `oauth_mcp` na dev ma DCR/PKCE/loopback/rotujący refresh).

**Tech Stack:** Python ≥3.10, stdlib (`http.server`, `webbrowser`, `secrets`, `hashlib`, `os`, `json`, `asyncio`), istniejące `httpx` + `mcp[cli]>=1.28`. Testy: `pytest` + `respx` (offline). **Bez nowych zależności.**

## Global Constraints

- Max line length: 88 (ruff; `ruff check` + `ruff format --check` muszą przejść).
- `requires-python >=3.10` — bez składni 3.11+.
- **Zero nowych zależności** — tylko stdlib + `httpx` + `mcp` (już w `dependencies`).
- Żadnego bare `except`/`except Exception: pass` — wąskie typy, każdy z komunikatem lub re-raise.
- Testy offline (respx); żadnych żywych wywołań sieciowych ani realnego `webbrowser`/loopbacku poza testem jednostkowym sterującym handlerem bezpośrednio.
- Izolacja testów store: każdy test ustawia `monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))` — nie dotykamy realnego `~/.config`.
- **Zero zmian w repo BPP.** Ten plan dotyka wyłącznie repo `bpp-mcp`.
- Worktree: `/Users/mpasternak/Programowanie/bpp-mcp-oauth-stdio`, branch `feat-oauth-stdio-login`.
- Spec: `docs/superpowers/specs/2026-07-11-mcp-oauth-stdio-login-design.md`.
- Po każdej implementacji: `uv run pytest -q` zielone przed commitem.

---

### Task 1: `token_store.py` — trwałość tokenów

**Files:**
- Create: `src/bpp_mcp/token_store.py`
- Test: `tests/test_token_store.py`

**Interfaces:**
- Produces:
  - `TokenSet` (dataclass): `base_url: str`, `access_token: str`, `refresh_token: str | None`, `expires_at: float`, `token_endpoint: str`, `username: str | None = None`, `client_id: str | None = None`; metoda `is_expired(skew: float = 60.0, *, now: float | None = None) -> bool`.
  - `store_path(base_url: str) -> Path`
  - `load(base_url: str) -> TokenSet | None`
  - `save(ts: TokenSet) -> None`
  - `clear(base_url: str) -> None`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_token_store.py
from __future__ import annotations

import json
import os
import stat

import pytest

from bpp_mcp import token_store
from bpp_mcp.token_store import TokenSet


@pytest.fixture(autouse=True)
def _izolacja(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))


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


def test_save_load_roundtrip():
    ts = _ts()
    token_store.save(ts)
    got = token_store.load(ts.base_url)
    assert got == ts


def test_save_ustawia_uprawnienia_0600():
    ts = _ts()
    token_store.save(ts)
    path = token_store.store_path(ts.base_url)
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700


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
    assert ts.is_expired(now=999.0) is True       # 1000 - 60 <= 999
    assert ts.is_expired(now=900.0) is False      # 1000 - 60 = 940 > 900
    assert ts.is_expired(skew=0.0, now=999.0) is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/mpasternak/Programowanie/bpp-mcp-oauth-stdio && uv run pytest tests/test_token_store.py -q`
Expected: FAIL (`ModuleNotFoundError: bpp_mcp.token_store`).

- [ ] **Step 3: Write minimal implementation**

```python
# src/bpp_mcp/token_store.py
"""Trwały, per-instancja cache tokenów OAuth (tryb stdio self-login).

Plik ``~/.config/bpp-mcp/<sha256(base_url)[:16]>/tokens.json`` (chmod 600,
katalog 700, zapis atomowy). Klucz per-instancja izoluje tożsamości różnych
wdrożeń BPP. Bez I/O sieciowego — to tylko warstwa dyskowa.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from dataclasses import asdict, dataclass
from pathlib import Path

_REQUIRED = ("base_url", "access_token", "expires_at", "token_endpoint")


@dataclass
class TokenSet:
    base_url: str
    access_token: str
    refresh_token: str | None
    expires_at: float
    token_endpoint: str
    username: str | None = None
    client_id: str | None = None

    def is_expired(self, skew: float = 60.0, *, now: float | None = None) -> bool:
        current = time.time() if now is None else now
        return self.expires_at - skew <= current


def _config_home() -> Path:
    xdg = os.environ.get("XDG_CONFIG_HOME")
    return Path(xdg) if xdg else Path.home() / ".config"


def store_path(base_url: str) -> Path:
    klucz = hashlib.sha256(base_url.encode("utf-8")).hexdigest()[:16]
    return _config_home() / "bpp-mcp" / klucz / "tokens.json"


def load(base_url: str) -> TokenSet | None:
    path = store_path(base_url)
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
        return None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict) or any(k not in data for k in _REQUIRED):
        return None
    return TokenSet(
        base_url=data["base_url"],
        access_token=data["access_token"],
        refresh_token=data.get("refresh_token"),
        expires_at=float(data["expires_at"]),
        token_endpoint=data["token_endpoint"],
        username=data.get("username"),
        client_id=data.get("client_id"),
    )


def save(ts: TokenSet) -> None:
    path = store_path(ts.base_url)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(path.parent, 0o700)
    tmp = path.with_suffix(".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(asdict(ts), fh)
    os.replace(tmp, path)  # atomowo; zachowuje 0600 z tmp


def clear(base_url: str) -> None:
    try:
        store_path(base_url).unlink()
    except FileNotFoundError:
        pass  # już usunięty — logout idempotentny
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_token_store.py -q`
Expected: PASS (8 passed).

- [ ] **Step 5: Commit**

```bash
git add src/bpp_mcp/token_store.py tests/test_token_store.py
git commit -m "feat(token_store): per-instancja cache tokenów OAuth (chmod 600, atomic)"
```

---

### Task 2: `oauth_client.py` — discovery / DCR / PKCE / token / refresh

**Files:**
- Create: `src/bpp_mcp/oauth_client.py`
- Test: `tests/test_oauth_client.py`

**Interfaces:**
- Consumes: `token_store.TokenSet`.
- Produces:
  - `Metadata` (dataclass): `authorization_endpoint: str`, `token_endpoint: str`, `registration_endpoint: str | None`.
  - `discover(base_url: str, *, client: httpx.Client | None = None) -> Metadata`
  - `register_client(meta: Metadata, redirect_uri: str, *, client_name: str = "bpp-mcp", client: httpx.Client | None = None) -> str`
  - `_pkce() -> tuple[str, str]` (verifier, challenge)
  - `refresh(ts: TokenSet, *, client: httpx.Client | None = None) -> TokenSet`
  - `RefreshFailed(Exception)`
  - `_whoami(base_url: str, access_token: str, *, client: httpx.Client | None = None) -> str | None`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_oauth_client.py
from __future__ import annotations

import base64
import hashlib

import httpx
import pytest
import respx

from bpp_mcp import oauth_client
from bpp_mcp.oauth_client import Metadata, RefreshFailed
from bpp_mcp.token_store import TokenSet

BASE = "https://bpp.test"
META_URL = f"{BASE}/.well-known/oauth-authorization-server"


def _meta_body():
    return {
        "issuer": BASE,
        "authorization_endpoint": f"{BASE}/o/authorize/",
        "token_endpoint": f"{BASE}/o/token/",
        "registration_endpoint": f"{BASE}/o/register/",
        "code_challenge_methods_supported": ["S256"],
    }


@respx.mock
def test_discover():
    respx.get(META_URL).mock(return_value=httpx.Response(200, json=_meta_body()))
    meta = oauth_client.discover(BASE)
    assert meta.authorization_endpoint == f"{BASE}/o/authorize/"
    assert meta.token_endpoint == f"{BASE}/o/token/"
    assert meta.registration_endpoint == f"{BASE}/o/register/"


@respx.mock
def test_register_client():
    meta = Metadata(f"{BASE}/o/authorize/", f"{BASE}/o/token/", f"{BASE}/o/register/")
    route = respx.post(f"{BASE}/o/register/").mock(
        return_value=httpx.Response(201, json={"client_id": "CID123"})
    )
    cid = oauth_client.register_client(meta, "http://127.0.0.1:5000/callback")
    assert cid == "CID123"
    sent = route.calls.last.request
    assert b"127.0.0.1:5000/callback" in sent.content


def test_pkce_challenge_is_s256_of_verifier():
    verifier, challenge = oauth_client._pkce()
    oczek = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest())
        .rstrip(b"=")
        .decode("ascii")
    )
    assert challenge == oczek


@respx.mock
def test_refresh_rotuje_i_zwraca_nowy_tokenset():
    ts = TokenSet(
        base_url=BASE,
        access_token="STARY",
        refresh_token="RT_STARY",
        expires_at=0.0,
        token_endpoint=f"{BASE}/o/token/",
        username="k",
        client_id="CID",
    )
    respx.post(f"{BASE}/o/token/").mock(
        return_value=httpx.Response(
            200,
            json={
                "access_token": "NOWY",
                "refresh_token": "RT_NOWY",
                "expires_in": 1800,
            },
        )
    )
    new = oauth_client.refresh(ts)
    assert new.access_token == "NOWY"
    assert new.refresh_token == "RT_NOWY"     # rotacja zapisana
    assert new.token_endpoint == ts.token_endpoint
    assert new.client_id == "CID"
    assert new.expires_at > ts.expires_at


@respx.mock
def test_refresh_odrzucony_podnosi_refreshfailed():
    ts = TokenSet(
        base_url=BASE,
        access_token="A",
        refresh_token="RT",
        expires_at=0.0,
        token_endpoint=f"{BASE}/o/token/",
        client_id="CID",
    )
    respx.post(f"{BASE}/o/token/").mock(
        return_value=httpx.Response(400, json={"error": "invalid_grant"})
    )
    with pytest.raises(RefreshFailed):
        oauth_client.refresh(ts)


def test_refresh_bez_refresh_tokenu_podnosi():
    ts = TokenSet(
        base_url=BASE,
        access_token="A",
        refresh_token=None,
        expires_at=0.0,
        token_endpoint=f"{BASE}/o/token/",
    )
    with pytest.raises(RefreshFailed):
        oauth_client.refresh(ts)


@respx.mock
def test_whoami_zwraca_username_lub_none():
    respx.get(f"{BASE}/api/v1/whoami/").mock(
        return_value=httpx.Response(200, json={"id": 1, "username": "nowak"})
    )
    assert oauth_client._whoami(BASE, "AT") == "nowak"


@respx.mock
def test_whoami_nie200_none():
    respx.get(f"{BASE}/api/v1/whoami/").mock(return_value=httpx.Response(500))
    assert oauth_client._whoami(BASE, "AT") is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_oauth_client.py -q`
Expected: FAIL (`ModuleNotFoundError: bpp_mcp.oauth_client`).

- [ ] **Step 3: Write minimal implementation**

```python
# src/bpp_mcp/oauth_client.py
"""OAuth 2.1 public client (native-app flow, RFC 8252) dla trybu stdio.

Kroki rozbite na małe, osobno testowalne funkcje: ``discover`` (AS-metadata,
RFC 8414), ``register_client`` (DCR, RFC 7591), ``_pkce`` (S256),
``refresh`` (rotujący refresh) oraz ``login`` (orkiestracja loopback+browser,
patrz Task 3). Sieć przez ``httpx`` (wstrzykiwalny ``client`` do testów).
"""

from __future__ import annotations

import base64
import hashlib
import secrets
import time
from dataclasses import dataclass

import httpx

from .token_store import TokenSet

_TIMEOUT = httpx.Timeout(10.0, connect=5.0)


class RefreshFailed(Exception):
    """Odświeżenie tokenu nieudane (brak/nieważny refresh, sieć)."""


@dataclass
class Metadata:
    authorization_endpoint: str
    token_endpoint: str
    registration_endpoint: str | None


def _client_ctx(client: httpx.Client | None) -> tuple[httpx.Client, bool]:
    if client is not None:
        return client, False
    return httpx.Client(timeout=_TIMEOUT, follow_redirects=True), True


def discover(base_url: str, *, client: httpx.Client | None = None) -> Metadata:
    url = f"{base_url.rstrip('/')}/.well-known/oauth-authorization-server"
    cli, owns = _client_ctx(client)
    try:
        resp = cli.get(url)
        resp.raise_for_status()
        data = resp.json()
    finally:
        if owns:
            cli.close()
    return Metadata(
        authorization_endpoint=data["authorization_endpoint"],
        token_endpoint=data["token_endpoint"],
        registration_endpoint=data.get("registration_endpoint"),
    )


def register_client(
    meta: Metadata,
    redirect_uri: str,
    *,
    client_name: str = "bpp-mcp",
    client: httpx.Client | None = None,
) -> str:
    if not meta.registration_endpoint:
        raise RuntimeError("Instancja BPP nie udostępnia rejestracji (DCR).")
    cli, owns = _client_ctx(client)
    try:
        resp = cli.post(
            meta.registration_endpoint,
            json={"client_name": client_name, "redirect_uris": [redirect_uri]},
        )
        resp.raise_for_status()
        return resp.json()["client_id"]
    finally:
        if owns:
            cli.close()


def _pkce() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return verifier, challenge


def _exchange(
    token_endpoint: str, data: dict, *, client: httpx.Client | None = None
) -> dict:
    cli, owns = _client_ctx(client)
    try:
        resp = cli.post(token_endpoint, data=data)
        resp.raise_for_status()
        return resp.json()
    finally:
        if owns:
            cli.close()


def _whoami(
    base_url: str, access_token: str, *, client: httpx.Client | None = None
) -> str | None:
    cli, owns = _client_ctx(client)
    try:
        resp = cli.get(
            f"{base_url.rstrip('/')}/api/v1/whoami/",
            headers={
                "Authorization": f"Bearer {access_token}",
                "Accept": "application/json",
            },
        )
        if resp.status_code != 200:
            return None
        return resp.json().get("username")
    except httpx.HTTPError:
        return None  # tożsamość jest miękka — nie wywraca loginu
    finally:
        if owns:
            cli.close()


def refresh(ts: TokenSet, *, client: httpx.Client | None = None) -> TokenSet:
    if not ts.refresh_token:
        raise RefreshFailed("Brak refresh_token — wymagane ponowne logowanie.")
    try:
        tok = _exchange(
            ts.token_endpoint,
            {
                "grant_type": "refresh_token",
                "refresh_token": ts.refresh_token,
                "client_id": ts.client_id or "",
            },
            client=client,
        )
    except httpx.HTTPStatusError as exc:
        raise RefreshFailed(
            f"Odświeżenie odrzucone ({exc.response.status_code})."
        ) from exc
    except httpx.HTTPError as exc:
        raise RefreshFailed(f"Błąd sieci przy odświeżaniu: {exc}") from exc
    return TokenSet(
        base_url=ts.base_url,
        access_token=tok["access_token"],
        refresh_token=tok.get("refresh_token") or ts.refresh_token,
        expires_at=time.time() + float(tok.get("expires_in", 0)),
        token_endpoint=ts.token_endpoint,
        username=ts.username,
        client_id=ts.client_id,
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_oauth_client.py -q`
Expected: PASS (8 passed).

- [ ] **Step 5: Commit**

```bash
git add src/bpp_mcp/oauth_client.py tests/test_oauth_client.py
git commit -m "feat(oauth_client): discover/DCR/PKCE/refresh (public client)"
```

---

### Task 3: `oauth_client.login` — orkiestracja loopback + PKCE

**Files:**
- Modify: `src/bpp_mcp/oauth_client.py` (dołóż loopback + `login`)
- Test: `tests/test_oauth_login.py`

**Interfaces:**
- Produces: `login(base_url: str, *, existing_client_id: str | None = None, timeout: float = 300.0, open_browser=webbrowser.open) -> TokenSet`

**Uwaga testowa:** `login` startuje realny loopback `HTTPServer` na `127.0.0.1:0`
(lokalny, natychmiastowy — to NIE jest wywołanie sieciowe na zewnątrz). `webbrowser`
wstrzykujemy: zamiast otwierać przeglądarkę, testowy `open_browser` w osobnym wątku
uderza w callback URL, symulując powrót z AS. Discovery/DCR/token mockujemy przez respx.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_oauth_login.py
from __future__ import annotations

import threading
import urllib.parse

import httpx
import pytest
import respx

from bpp_mcp import oauth_client

BASE = "https://bpp.test"


def _meta():
    respx.get(f"{BASE}/.well-known/oauth-authorization-server").mock(
        return_value=httpx.Response(
            200,
            json={
                "authorization_endpoint": f"{BASE}/o/authorize/",
                "token_endpoint": f"{BASE}/o/token/",
                "registration_endpoint": f"{BASE}/o/register/",
            },
        )
    )


def _fake_browser(*, code="KOD", tamper_state=False):
    """Zwróć callable udające webbrowser.open: parsuje authorize URL,
    w osobnym wątku uderza w loopback callback z code+state."""

    def _open(url: str) -> bool:
        q = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
        redirect = q["redirect_uri"][0]
        state = "ZLE" if tamper_state else q["state"][0]

        def _hit():
            cb = f"{redirect}?code={code}&state={state}"
            httpx.get(cb)  # loopback — lokalny serwer login()

        threading.Thread(target=_hit, daemon=True).start()
        return True

    return _open


@respx.mock
def test_login_pelny_flow(monkeypatch):
    _meta()
    respx.post(f"{BASE}/o/register/").mock(
        return_value=httpx.Response(201, json={"client_id": "CID"})
    )
    respx.post(f"{BASE}/o/token/").mock(
        return_value=httpx.Response(
            200,
            json={"access_token": "AT", "refresh_token": "RT", "expires_in": 1800},
        )
    )
    respx.get(f"{BASE}/api/v1/whoami/").mock(
        return_value=httpx.Response(200, json={"id": 3, "username": "dabrowski"})
    )
    # respx nie przechwytuje loopbacku 127.0.0.1 — pass_through dla niego:
    respx.route(host="127.0.0.1").pass_through()

    ts = oauth_client.login(BASE, open_browser=_fake_browser(), timeout=10.0)
    assert ts.access_token == "AT"
    assert ts.refresh_token == "RT"
    assert ts.username == "dabrowski"
    assert ts.client_id == "CID"
    assert ts.token_endpoint == f"{BASE}/o/token/"


@respx.mock
def test_login_zly_state_odrzucony():
    _meta()
    respx.post(f"{BASE}/o/register/").mock(
        return_value=httpx.Response(201, json={"client_id": "CID"})
    )
    respx.route(host="127.0.0.1").pass_through()
    with pytest.raises(ValueError):
        oauth_client.login(
            BASE, open_browser=_fake_browser(tamper_state=True), timeout=10.0
        )


@respx.mock
def test_login_timeout_bez_callbacku():
    _meta()
    respx.post(f"{BASE}/o/register/").mock(
        return_value=httpx.Response(201, json={"client_id": "CID"})
    )
    with pytest.raises(TimeoutError):
        oauth_client.login(BASE, open_browser=lambda url: True, timeout=0.4)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_oauth_login.py -q`
Expected: FAIL (`AttributeError: module 'bpp_mcp.oauth_client' has no attribute 'login'`).

- [ ] **Step 3: Write minimal implementation**

Dołóż na górze importy i klasy loopbacku, oraz funkcję `login` na końcu modułu:

```python
# --- dopisz do importów w src/bpp_mcp/oauth_client.py ---
import queue
import threading
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer

_STRONA_OK = (
    "<!doctype html><meta charset='utf-8'>"
    "<h1>Zalogowano do BPP</h1><p>Możesz wrócić do Claude i zamknąć tę kartę.</p>"
)


class _CallbackHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802 (API http.server)
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path != "/callback":
            self.send_response(404)
            self.end_headers()
            return
        params = urllib.parse.parse_qs(parsed.query)
        self.server.wynik.put(params)  # type: ignore[attr-defined]
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(_STRONA_OK.encode("utf-8"))

    def log_message(self, *args: object) -> None:
        pass  # cisza — nie zaśmiecaj stderr logami http.server


def _start_loopback() -> tuple[HTTPServer, int]:
    server = HTTPServer(("127.0.0.1", 0), _CallbackHandler)
    server.wynik = queue.Queue()  # type: ignore[attr-defined]
    port = server.server_address[1]
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, port


def login(
    base_url: str,
    *,
    existing_client_id: str | None = None,
    timeout: float = 300.0,
    open_browser=webbrowser.open,
) -> TokenSet:
    base_url = base_url.rstrip("/")
    meta = discover(base_url)
    server, port = _start_loopback()
    redirect_uri = f"http://127.0.0.1:{port}/callback"
    try:
        client_id = existing_client_id or register_client(meta, redirect_uri)
        verifier, challenge = _pkce()
        state = secrets.token_urlsafe(32)
        query = urllib.parse.urlencode(
            {
                "response_type": "code",
                "client_id": client_id,
                "redirect_uri": redirect_uri,
                "scope": "read",
                "state": state,
                "code_challenge": challenge,
                "code_challenge_method": "S256",
            }
        )
        open_browser(f"{meta.authorization_endpoint}?{query}")
        try:
            params = server.wynik.get(timeout=timeout)  # type: ignore[attr-defined]
        except queue.Empty as exc:
            raise TimeoutError(
                "Nie odebrano odpowiedzi logowania w wyznaczonym czasie."
            ) from exc
        if (params.get("state") or [None])[0] != state:
            raise ValueError("Niezgodny parametr state — logowanie odrzucone.")
        code = (params.get("code") or [None])[0]
        if not code:
            blad = (params.get("error") or ["brak parametru code"])[0]
            raise ValueError(f"Logowanie nie powiodło się: {blad}.")
    finally:
        server.shutdown()
        server.server_close()
    tok = _exchange(
        meta.token_endpoint,
        {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri,
            "client_id": client_id,
            "code_verifier": verifier,
        },
    )
    return TokenSet(
        base_url=base_url,
        access_token=tok["access_token"],
        refresh_token=tok.get("refresh_token"),
        expires_at=time.time() + float(tok.get("expires_in", 0)),
        token_endpoint=meta.token_endpoint,
        username=_whoami(base_url, tok["access_token"]),
        client_id=client_id,
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_oauth_login.py -q`
Expected: PASS (3 passed). Jeśli `test_login_timeout` bywa wolny — to celowe (0.4 s).

- [ ] **Step 5: Commit**

```bash
git add src/bpp_mcp/oauth_client.py tests/test_oauth_login.py
git commit -m "feat(oauth_client): login() — loopback callback + PKCE + state"
```

---

### Task 4: `login_state.TokenProvider` — async dostarczanie bearera

**Files:**
- Create: `src/bpp_mcp/login_state.py`
- Test: `tests/test_login_state.py`

**Interfaces:**
- Consumes: `token_store` (`load`/`save`/`clear`, `TokenSet`), `oauth_client.refresh`, `oauth_client.RefreshFailed`.
- Produces: `TokenProvider(base_url: str, *, refresh_fn=oauth_client.refresh)`; `async def bearer(self) -> str | None`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_login_state.py
from __future__ import annotations

import asyncio
import time

import pytest

from bpp_mcp import login_state, token_store
from bpp_mcp.oauth_client import RefreshFailed
from bpp_mcp.token_store import TokenSet


@pytest.fixture(autouse=True)
def _izolacja(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))


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
async def test_wygasly_odswieza_zapisuje_i_zwraca(monkeypatch):
    token_store.save(_ts(access="STARY", expires_at=0.0))
    licznik = {"n": 0}

    def _fake_refresh(ts):
        licznik["n"] += 1
        return _ts(access="NOWY")

    prov = login_state.TokenProvider(BASE, refresh_fn=_fake_refresh)
    got = await prov.bearer()
    assert got == "NOWY"
    assert licznik["n"] == 1
    # zapisany do store (rotacja utrwalona):
    assert token_store.load(BASE).access_token == "NOWY"


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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_login_state.py -q`
Expected: FAIL (`ModuleNotFoundError: bpp_mcp.login_state`).

- [ ] **Step 3: Write minimal implementation**

```python
# src/bpp_mcp/login_state.py
"""Dostarczanie Bearera dla żądań w trybie stdio.

``TokenProvider`` czyta token ze store raz (przy tworzeniu, w lifespanie
serwera), zwraca access-token, a przy wygaśnięciu odświeża go POD ``asyncio.Lock``
(serializacja — rotujący refresh nie znosi refreshu równoległego) i utrwala nowy
zestaw. Refresh (sync, ``httpx``) uruchamiamy przez ``asyncio.to_thread``, by nie
blokować pętli zdarzeń.
"""

from __future__ import annotations

import asyncio
import sys

from . import oauth_client, token_store


class TokenProvider:
    def __init__(self, base_url: str, *, refresh_fn=oauth_client.refresh) -> None:
        self._base_url = base_url
        self._refresh_fn = refresh_fn
        self._lock = asyncio.Lock()
        self._ts = token_store.load(base_url)

    async def bearer(self) -> str | None:
        ts = self._ts
        if ts is None:
            return None
        if not ts.is_expired():
            return ts.access_token
        async with self._lock:
            ts = self._ts  # inny coroutine mógł już odświeżyć
            if ts is None:
                return None
            if not ts.is_expired():
                return ts.access_token
            try:
                nowy = await asyncio.to_thread(self._refresh_fn, ts)
            except oauth_client.RefreshFailed as exc:
                token_store.clear(self._base_url)
                self._ts = None
                print(
                    f"bpp-mcp: sesja wygasła ({exc}) — tryb anonimowy. "
                    "Zaloguj ponownie: bpp-mcp login",
                    file=sys.stderr,
                )
                return None
            token_store.save(nowy)
            self._ts = nowy
            return nowy.access_token
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_login_state.py -q`
Expected: PASS (5 passed).

- [ ] **Step 5: Commit**

```bash
git add src/bpp_mcp/login_state.py tests/test_login_state.py
git commit -m "feat(login_state): TokenProvider — bearer ze store + refresh pod lockiem"
```

---

### Task 5: Wpięcie w `server.py` — `_client` async + provider w lifespanie

**Files:**
- Modify: `src/bpp_mcp/server.py` (import, `KontekstApp`, `_client`, `lifespan`, 10 wrapperów, `build_mcp`)
- Test: `tests/test_stdio_login.py`

**Interfaces:**
- Consumes: `login_state.TokenProvider`, `auth.bearer_from_request`, `auth.set_current_bearer`.
- Produces: `_client(ctx)` jest teraz `async`; `KontekstApp.bearer_provider: TokenProvider | None`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_stdio_login.py
from __future__ import annotations

import types

import pytest

from bpp_mcp import auth
from bpp_mcp.server import KontekstApp, _client


class _FakeProvider:
    def __init__(self, token):
        self._token = token

    async def bearer(self):
        return self._token


def _ctx(*, request, provider):
    kctx = KontekstApp(client="SENTINEL", bearer_provider=provider)
    rc = types.SimpleNamespace(request=request, lifespan_context=kctx)
    return types.SimpleNamespace(request_context=rc)


@pytest.mark.asyncio
async def test_stdio_bierze_bearer_z_providera():
    auth.set_current_bearer(None)
    ctx = _ctx(request=None, provider=_FakeProvider("Z_CACHE"))
    assert await _client(ctx) == "SENTINEL"
    assert auth.current_bearer() == "Z_CACHE"
    auth.set_current_bearer(None)


@pytest.mark.asyncio
async def test_request_bearer_wygrywa_z_providerem():
    auth.set_current_bearer(None)
    req = types.SimpleNamespace(headers={"authorization": "Bearer Z_REQ"})
    ctx = _ctx(request=req, provider=_FakeProvider("Z_CACHE"))
    assert await _client(ctx) == "SENTINEL"
    assert auth.current_bearer() == "Z_REQ"   # http/request wygrywa
    auth.set_current_bearer(None)


@pytest.mark.asyncio
async def test_brak_providera_i_requestu_none():
    auth.set_current_bearer(None)
    ctx = _ctx(request=None, provider=None)
    assert await _client(ctx) == "SENTINEL"
    assert auth.current_bearer() is None
    auth.set_current_bearer(None)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_stdio_login.py -q`
Expected: FAIL (`TypeError: KontekstApp.__init__() got an unexpected keyword argument 'bearer_provider'` lub `_client` nie jest awaitable).

- [ ] **Step 3: Write minimal implementation**

W `src/bpp_mcp/server.py`:

(a) Import — dołóż `TokenProvider`:
```python
from .login_state import TokenProvider
```

(b) `KontekstApp` — dołóż pole:
```python
@dataclass
class KontekstApp:
    """Zawartość lifespan-context serwera — współdzielony klient HTTP oraz
    (w trybie stdio) provider tokenu OAuth z lokalnego cache."""

    client: BppClient
    bearer_provider: TokenProvider | None = None
```

(c) `_client` — zamień na async z fallbackiem na provider:
```python
async def _client(ctx: Context) -> BppClient:
    """Zwróć współdzielony klient i ustaw token bieżącego żądania.

    Kolejność: token z nagłówka bieżącego requestu (tryb http, K1) wygrywa;
    w stdio, gdy go brak, sięgamy do lokalnego cache przez ``bearer_provider``
    (może odświeżyć token). Brak obu → anonimowo (``None``)."""
    request = getattr(ctx.request_context, "request", None)
    bearer = bearer_from_request(request)
    kctx = ctx.request_context.lifespan_context
    if bearer is None and kctx.bearer_provider is not None:
        bearer = await kctx.bearer_provider.bearer()
    set_current_bearer(bearer)
    return kctx.client
```

(d) 10 wrapperów — zamień `_client(ctx)` na `await _client(ctx)`. Dotyczy:
`szukaj_publikacji`, `szukaj_autora`, `publikacje_autora`, `publikacje_jednostki`,
`pobierz_rekord`, `lista_publikacji`, `slownik`, `zapytanie_rekord`,
`zapytanie_autor`, `zapytanie_autorzy`. (NIE `djangoql_schema` — nie woła `_client`.)

Przykład (zastosuj analogicznie do każdego z 10):
```python
async def szukaj_publikacji(
    ctx: Context,
    q: str,
    rok_od: int | None = None,
    rok_do: int | None = None,
    limit: int = 25,
) -> dict[str, Any]:
    """Rankowane wyszukiwanie pełnotekstowe publikacji w BPP (endpoint
    /szukaj/). Wymaga instancji BPP z Fazą 0 — inaczej zwraca czytelny błąd."""
    return await tools.szukaj_publikacji(await _client(ctx), q, rok_od, rok_do, limit)
```

(e) `lifespan` w `build_mcp` — buduj provider dla stdio:
```python
    @asynccontextmanager
    async def lifespan(_server: FastMCP) -> AsyncIterator[KontekstApp]:
        client = BppClient(config)
        provider = TokenProvider(config.base_url) if config.transport != "http" else None
        try:
            yield KontekstApp(client=client, bearer_provider=provider)
        finally:
            await client.aclose()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_stdio_login.py tests/test_server.py tests/test_http_auth.py -q`
Expected: PASS (nowe 3 + istniejące serwera/http nadal zielone — `test_http_auth` sprawdza ścieżkę request-bearer, która wciąż wygrywa).

- [ ] **Step 5: Commit**

```bash
git add src/bpp_mcp/server.py tests/test_stdio_login.py
git commit -m "feat(server): _client async + TokenProvider w lifespanie (stdio bearer)"
```

---

### Task 6: CLI `bpp-mcp login` / `logout`

**Files:**
- Modify: `src/bpp_mcp/server.py` (`main`, dołóż `_cmd_login`, importy)
- Test: `tests/test_cli.py`

**Interfaces:**
- Consumes: `oauth_client.login`, `token_store.load`/`clear`/`save`, `Config.from_env`.
- Produces: `main()` z podkomendami `login`/`logout`; `_cmd_login(config: Config) -> None`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_cli.py
from __future__ import annotations

import pytest

from bpp_mcp import server, token_store
from bpp_mcp.config import Config
from bpp_mcp.token_store import TokenSet

BASE = "https://bpp.test"


@pytest.fixture(autouse=True)
def _izolacja(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
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
    assert "dabrowski" in capsys.readouterr().out


def test_cmd_login_reuzywa_client_id(monkeypatch):
    token_store.save(_ts())  # ma client_id=CID
    widziane = {}

    def _fake_login(base_url, *, existing_client_id=None):
        widziane["cid"] = existing_client_id
        return _ts()

    monkeypatch.setattr(server.oauth_client, "login", _fake_login)
    server._cmd_login(Config.from_env())
    assert widziane["cid"] == "CID"


def test_main_login(monkeypatch):
    called = {}
    monkeypatch.setattr(server, "_cmd_login", lambda cfg: called.setdefault("login", cfg))
    monkeypatch.setattr("sys.argv", ["bpp-mcp", "login"])
    server.main()
    assert "login" in called


def test_main_logout_czysci(monkeypatch, capsys):
    token_store.save(_ts())
    monkeypatch.setattr("sys.argv", ["bpp-mcp", "logout"])
    server.main()
    assert token_store.load(BASE) is None


def test_main_bez_podkomendy_uruchamia_serwer(monkeypatch):
    uruchomiono = {}
    monkeypatch.setattr("sys.argv", ["bpp-mcp"])
    monkeypatch.setattr(server.mcp, "run", lambda *a, **k: uruchomiono.setdefault("run", True))
    server.main()
    assert uruchomiono.get("run") is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_cli.py -q`
Expected: FAIL (`AttributeError: module 'bpp_mcp.server' has no attribute '_cmd_login'` / brak importu `oauth_client`).

- [ ] **Step 3: Write minimal implementation**

W `src/bpp_mcp/server.py`:

(a) Importy — dołóż:
```python
import sys

import httpx

from . import oauth_client, token_store
```

(b) Dołóż `_cmd_login` (nad `main`):
```python
def _cmd_login(config: Config) -> None:
    """Przeprowadź logowanie OAuth i zapisz token do lokalnego cache."""
    istniejacy = token_store.load(config.base_url)
    try:
        ts = oauth_client.login(
            config.base_url,
            existing_client_id=istniejacy.client_id if istniejacy else None,
        )
    except (httpx.HTTPError, ValueError, TimeoutError, RuntimeError) as exc:
        print(f"Logowanie nieudane: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
    token_store.save(ts)
    kto = ts.username or "(nieznany użytkownik)"
    print(f"Zalogowano jako {kto} @ {config.base_url}")
```

(c) Zamień `main` na wersję z podkomendami:
```python
def main() -> None:
    """``bpp-mcp``: bez podkomendy → serwer (stdio; ``--http`` → Streamable HTTP
    + OAuth RS). ``login`` → logowanie w przeglądarce; ``logout`` → wyczyść token."""
    parser = argparse.ArgumentParser(prog="bpp-mcp")
    parser.add_argument(
        "--http", action="store_true", help="Streamable HTTP + OAuth (Resource Server)."
    )
    parser.add_argument("--host", default=None, help="Host HTTP (dom. 127.0.0.1).")
    parser.add_argument("--port", type=int, default=None, help="Port HTTP.")
    sub = parser.add_subparsers(dest="cmd")
    sub.add_parser("login", help="Zaloguj się do BPP (przeglądarka) i zapisz token.")
    sub.add_parser("logout", help="Usuń zapisany token tej instancji BPP.")
    args = parser.parse_args()
    config = Config.from_env()

    if args.cmd == "login":
        _cmd_login(config)
        return
    if args.cmd == "logout":
        token_store.clear(config.base_url)
        print(f"Wylogowano z {config.base_url}")
        return

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

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_cli.py -q`
Expected: PASS (5 passed).

- [ ] **Step 5: Commit**

```bash
git add src/bpp_mcp/server.py tests/test_cli.py
git commit -m "feat(cli): podkomendy bpp-mcp login / logout"
```

---

### Task 7: Hybrydowa podpowiedź `login` przy 401 w `zapytanie_*`

**Files:**
- Modify: `src/bpp_mcp/client.py` (dołóż property `transport`)
- Modify: `src/bpp_mcp/tools.py` (`_blad_zapytania` przyjmuje `stdio`; `_zapytanie` przekazuje)
- Test: `tests/test_zapytanie.py` (dopisz 2 testy)

**Interfaces:**
- Consumes: `BppClient.transport` (nowa property, zwraca `"stdio"`/`"http"`).
- Produces: `_blad_zapytania(exc, *, stdio: bool = False)`.

**Uzasadnienie odstępstwa od specu:** hint wiążemy z transportem+statusem, nie z
przeszukiwaniem store z warstwy narzędzi. `stdio`+401 → „zaloguj się" (brak/wygasł
token); 403 zostaje bez zmian (użytkownik zalogowany, brak uprawnień redaktora —
`login` nie pomoże). W trybie http komunikat bez zmian (klient MCP zarządza auth).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_zapytanie.py — DOPISZ na końcu pliku

import httpx
import respx

from bpp_mcp.client import BppClient
from bpp_mcp.config import Config


@respx.mock
async def test_zapytanie_401_stdio_podpowiada_login():
    cfg = Config(base_url="https://bpp.test", transport="stdio")
    respx.get(url__regex=r".*/zapytanie/rekord/.*").mock(
        return_value=httpx.Response(401, json={"detail": "nieautoryzowany"})
    )
    async with BppClient(cfg, backoff_base=0.0) as c:
        from bpp_mcp import tools

        try:
            await tools.zapytanie_rekord(c, "rok = 2026")
            assert False, "oczekiwano BppError"
        except tools.BppError as exc:
            assert exc.status_code == 401
            assert "bpp-mcp login" in str(exc)


@respx.mock
async def test_zapytanie_401_http_bez_podpowiedzi_login():
    cfg = Config(base_url="https://bpp.test", transport="http")
    respx.get(url__regex=r".*/zapytanie/rekord/.*").mock(
        return_value=httpx.Response(401, json={"detail": "nieautoryzowany"})
    )
    # w http klient nie ma bearera w kontekście → _auth_kwargs podniesie BppError
    # ZANIM poleci żądanie; ustawiamy bearer, by dojść do 401 z serwera:
    from bpp_mcp.auth import set_current_bearer

    set_current_bearer("DUMMY")
    try:
        async with BppClient(cfg, backoff_base=0.0) as c:
            from bpp_mcp import tools

            try:
                await tools.zapytanie_rekord(c, "rok = 2026")
                assert False, "oczekiwano BppError"
            except tools.BppError as exc:
                assert exc.status_code == 401
                assert "bpp-mcp login" not in str(exc)
    finally:
        set_current_bearer(None)
```

(Uwaga: `tools` eksponuje `BppError` przez import — jeśli nie, użyj
`from bpp_mcp.client import BppError`. Sprawdź istniejące importy w
`tests/test_zapytanie.py` i użyj tej samej ścieżki.)

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_zapytanie.py -q -k "podpowiada_login or bez_podpowiedzi"`
Expected: FAIL (401 w stdio nie zawiera „bpp-mcp login").

- [ ] **Step 3: Write minimal implementation**

(a) W `src/bpp_mcp/client.py` — dołóż property w klasie `BppClient` (np. tuż po `aclose`):
```python
    @property
    def transport(self) -> str:
        """Tryb transportu (``stdio``/``http``) — steruje hybrydową
        podpowiedzią logowania w narzędziach zapytań."""
        return self._transport
```

(b) W `src/bpp_mcp/tools.py` — `_blad_zapytania`: zmień sygnaturę i gałąź 401:
```python
def _blad_zapytania(exc: BppError, *, stdio: bool = False) -> BppError:
    """Zmapuj kod stanu odpowiedzi endpointu ``zapytanie/*`` na czytelny,
    „naprawialny" komunikat dla agenta. Zwraca NOWY :class:`BppError` dla
    znanych statusów (400/401/403/503); dla nieznanych zwraca ``exc`` bez zmian.
    W trybie stdio 401 podpowiada jednorazowe ``bpp-mcp login``.
    """
    status = exc.status_code
    if status == 400:
        info = exc.payload if isinstance(exc.payload, dict) else {}
        opis = info.get("error") or "niepoprawne zapytanie DjangoQL"
        line, column = info.get("line"), info.get("column")
        gdzie = f" (linia {line}, kolumna {column})" if line and column else ""
        return BppError(
            f"Zapytanie DjangoQL odrzucone{gdzie}: {opis}. Popraw zapytanie "
            "(nazwa pola/składnia; pola PII jak autor.email są zablokowane) i ponów.",
            status_code=400,
            payload=exc.payload,
        )
    if status == 401:
        if stdio:
            return BppError(
                "Nie jesteś zalogowany lub token wygasł (401). Zaloguj się raz: "
                "uruchom `bpp-mcp login` w terminalu, a potem ponów zapytanie.",
                status_code=401,
            )
        return BppError(
            "Nieprawidłowy lub wygasły token (401) — wymagane ponowne "
            "uwierzytelnienie OAuth (endpoint /o/ instancji BPP).",
            status_code=401,
        )
    if status == 403:
        return BppError(
            "Brak uprawnień do zapytań DjangoQL (403) — wymagany superuser albo "
            "staff w grupie „wprowadzanie danych”.",
            status_code=403,
        )
    if status == 503:
        return BppError(
            "Zapytanie trwało za długo (503, statement_timeout 8 s) — zawęź "
            "warunki (mniejszy zakres lat, bardziej selektywne pola).",
            status_code=503,
        )
    return exc
```

(c) W `src/bpp_mcp/tools.py` — `_zapytanie`: przekaż `stdio`:
```python
    except BppError as exc:
        if exc.status_code in (400, 401, 403, 503):
            raise _blad_zapytania(exc, stdio=client.transport == "stdio") from exc
        raise
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_zapytanie.py -q`
Expected: PASS (istniejące + 2 nowe).

- [ ] **Step 5: Commit**

```bash
git add src/bpp_mcp/client.py src/bpp_mcp/tools.py tests/test_zapytanie.py
git commit -m "feat(tools): stdio 401 podpowiada bpp-mcp login (hybryda)"
```

---

### Task 8: Dokumentacja — README + changelog

**Files:**
- Modify: `README.md`
- Modify (jeśli istnieje): `CHANGELOG.md` lub `src/**/newsfragments/` (sprawdź; jeśli brak — pomiń, nie twórz na siłę)

- [ ] **Step 1: Sprawdź konwencję changelogu**

Run: `ls CHANGELOG.md 2>/dev/null; find . -path ./node_modules -prune -o -name 'newsfragments' -type d -print 2>/dev/null | head`
Expected: prawdopodobnie brak — wtedy tylko README.

- [ ] **Step 2: Dodaj sekcję do README**

W `README.md`, po sekcji „### Tryb OAuth (HTTP, per-user)", dołóż:

```markdown
### Logowanie w trybie stdio (per-user, bez hostowania)

Domyślny tryb stdio może działać **z uprawnieniami zalogowanego użytkownika**
bez uruchamiania serwera HTTP. Zaloguj się **raz**:

```bash
uvx --from git+https://github.com/iplweb/bpp-mcp bpp-mcp login
```

Otworzy się przeglądarka na logowanie BPP (hasło/LDAP/Microsoft/ORCID/Keycloak)
i ekran zgody (scope `read`). Po zalogowaniu token trafia do lokalnego pliku
`~/.config/bpp-mcp/<instancja>/tokens.json` (uprawnienia `0600`), a `bpp-mcp`
uruchamiany przez Claude forwarduje go do `/api/v1/` — bez dodatkowych kroków.

Efekty:
- **bogatsze wyniki** istniejących narzędzi (rekordy widoczne dla Twojego konta),
- narzędzia **`zapytanie_rekord` / `zapytanie_autor` / `zapytanie_autorzy`**
  (wykonywanie DjangoQL) działają — wymagają zalogowania i uprawnień redaktora.

Wylogowanie (usuwa token tej instancji):
```bash
uvx --from git+https://github.com/iplweb/bpp-mcp bpp-mcp logout
```

Token jest krótkotrwały (access 30 min) i odświeżany po cichu (refresh 7 dni,
rotujący). Zmiana hasła lub dezaktywacja konta w BPP unieważnia go — wtedy
`bpp-mcp` wraca do trybu anonimowego, a narzędzia `zapytanie_*` poproszą o
ponowne `bpp-mcp login`.

**Różnica względem trybu HTTP:** natywny przycisk „authorize" w Claude (jak przy
GitHub) należy do trybu HTTP (sekcja wyżej) — wymaga działającego serwera pod
URL-em. Tryb stdio nie pokazuje tego przycisku; logowanie przeprowadza komenda
`bpp-mcp login`. Oba forwardują token do tego samego API i wykluczają zapis
(read-only serwerowo).
```

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "docs(readme): logowanie w trybie stdio (bpp-mcp login/logout)"
```

---

## Po wdrożeniu (przed PR)

- [ ] Pełna regresja: `uv run pytest -q` — wszystko zielone.
- [ ] Lint: `uv run ruff check .` oraz `uv run ruff format --check .` — czyste.
- [ ] Pre-commit: `uvx pre-commit run --all-files` — Passed.
- [ ] Smoke: `uv run bpp-mcp --help` pokazuje podkomendy `login`/`logout`;
  `uv run bpp-mcp login --help` nie wywala się.
- [ ] Push gałęzi `feat-oauth-stdio-login` → PR do `main` z opisem + linkiem do
  spec/plan.

## Self-Review (autor planu)

**Spec coverage:** §4 token_store → Task 1; §4 oauth_client (discover/DCR/PKCE/
refresh) → Task 2; §5 login flow (loopback) → Task 3; §4 TokenProvider → Task 4;
§4 wpięcie server `_client` async + lifespan → Task 5; §4 CLI login/logout →
Task 6; §4/§6 hybryda 401 → Task 7; §9 README → Task 8. §7 bezpieczeństwo pokryte
przez Task 1 (chmod/atomic) + Task 2/3 (PKCE/state/loopback). §8 testy — każdy
Task ma sekcję testów. Brak luk.

**Type consistency:** `TokenSet` (pola: base_url, access_token, refresh_token,
expires_at, token_endpoint, username, client_id) spójny w Tasks 1–6. `Metadata`
(authorization_endpoint, token_endpoint, registration_endpoint) spójny Task 2–3.
`TokenProvider(base_url, *, refresh_fn)` + `async bearer()` spójny Task 4–5.
`_blad_zapytania(exc, *, stdio)` spójny Task 7. `_client` async + `await` w 10
wrapperach spójny Task 5.

**Placeholder scan:** brak TBD/TODO; każdy krok kodu ma pełny kod, każdy test ma
pełną treść, każda komenda ma oczekiwany wynik.

---

## Poprawki po 2× adwersarialnym review Fable (MUST APPLY)

Oba review'y (SDK/OAuth + testy/pokrycie) uzgodnione. `W4` (reuse `client_id` z
nowym portem loopbacku) **odrzucone jako nie-bug**: DOT 3.3.0
`redirect_to_uri_allowed` jest port-agnostic dla `http://127.0.0.1`/`::1` (RFC
8252 §7.3, zweryfikowane w źródle). Plan używa `127.0.0.1` (NIE `localhost`,
który NIE jest port-agnostic) — reuse zostaje. Loopback-pod-respx zweryfikowany
probem: `respx.route(host="127.0.0.1").pass_through()` działa (respx 0.23.1).

Poniższe poprawki nadpisują odpowiednie fragmenty Tasków 1–7.

### [K1] Task 5 — napraw istniejący test `tests/test_http_auth.py`
Dopisz do **Files/Modify** Task 5: `tests/test_http_auth.py`. Test
`test_client_ustawia_bearer_z_biezacego_requestu` jest **synchroniczny** i
`_client` po zmianie na async zwróci coroutine → FAIL. Zamień go na:
```python
@pytest.mark.asyncio
async def test_client_ustawia_bearer_z_biezacego_requestu():
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
```
(Step 4 Task 5: uruchom też `tests/test_http_auth.py` — musi być zielony.)

### [K2] Task 1 — `store_path` normalizuje `base_url`
Trailing slash w `BPP_BASE_URL` rozjeżdżał hash zapisu vs odczytu. Zmień:
```python
def store_path(base_url: str) -> Path:
    klucz = hashlib.sha256(base_url.rstrip("/").encode("utf-8")).hexdigest()[:16]
    return _config_home() / "bpp-mcp" / klucz / "tokens.json"
```
Dodaj test: `assert token_store.store_path("https://x/") == token_store.store_path("https://x")`.

### [K3]+[W3] Task 4 — `bearer()` re-loaduje store (pod lockiem)
`TokenProvider` czytał store raz → token zapisany przez `bpp-mcp login` w trakcie
żywej sesji nie był podnoszony (hint „ponów" martwy); dodatkowo padły refresh
mógł skasować świeży token innego procesu. Zamień `bearer` na:
```python
    async def bearer(self) -> str | None:
        ts = self._ts
        if ts is not None and not ts.is_expired():
            return ts.access_token
        async with self._lock:
            # (K3) token mógł się pojawić (login w trakcie sesji) lub zmienić
            # (inny proces MCP na tym samym store) po starcie — re-load.
            dysk = token_store.load(self._base_url)
            if dysk is not None and (
                self._ts is None or dysk.access_token != self._ts.access_token
            ):
                self._ts = dysk
            ts = self._ts
            if ts is None:
                return None
            if not ts.is_expired():
                return ts.access_token
            try:
                nowy = await asyncio.to_thread(self._refresh_fn, ts)
            except oauth_client.RefreshFailed as exc:
                # (W3) nie kasuj świeżego tokenu, który zapisał inny proces.
                dysk = token_store.load(self._base_url)
                if dysk is not None and dysk.access_token != ts.access_token:
                    self._ts = dysk
                    if not dysk.is_expired():
                        return dysk.access_token
                token_store.clear(self._base_url)
                self._ts = None
                print(
                    f"bpp-mcp: sesja wygasła ({exc}) — tryb anonimowy. "
                    "Zaloguj ponownie: bpp-mcp login",
                    file=sys.stderr,
                )
                return None
            token_store.save(nowy)
            self._ts = nowy
            return nowy.access_token
```
Dodaj test: provider utworzony bez tokenu → `token_store.save(_ts())` z zewnątrz →
kolejny `await prov.bearer()` zwraca `"AT"` (re-load w trakcie sesji).

### [W1]+[D7] Task 1 — twarde 0600 przy nadpisie; `clear` sprząta tmp
`os.open(mode=…)` działa tylko przy tworzeniu — leftover `tokens.tmp` z 0644
przeżyłby. Wymuś `fchmod` i posprzątaj tmp:
```python
def save(ts: TokenSet) -> None:
    path = store_path(ts.base_url)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(path.parent, 0o700)
    tmp = path.with_suffix(".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    os.fchmod(fd, 0o600)  # wymuś 0600 nawet gdy tmp istniał z luźniejszymi prawami
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(asdict(ts), fh)
    os.replace(tmp, path)  # atomowo; zachowuje 0600 z tmp


def clear(base_url: str) -> None:
    path = store_path(base_url)
    for p in (path, path.with_suffix(".tmp")):
        try:
            p.unlink()
        except FileNotFoundError:
            pass
```
Dodaj test: `save` tokenem A → `save` tokenem B → `load().access_token == "B"`
oraz `S_IMODE == 0o600` (nadpis utrzymuje uprawnienia).

### [W2] Task 2 — test refresh BEZ rotacji (zachowuje stary RT)
```python
@respx.mock
def test_refresh_bez_rotacji_zachowuje_stary_rt():
    ts = TokenSet(
        base_url=BASE, access_token="A", refresh_token="RT_STARY", expires_at=0.0,
        token_endpoint=f"{BASE}/o/token/", client_id="CID",
    )
    respx.post(f"{BASE}/o/token/").mock(
        return_value=httpx.Response(200, json={"access_token": "NOWY", "expires_in": 1800})
    )
    assert oauth_client.refresh(ts).refresh_token == "RT_STARY"
```

### [W7]+[D-refresh] Task 2 — `register_client` dołącza treść błędu; `refresh` fail-fast na braku `client_id`
```python
def register_client(meta, redirect_uri, *, client_name="bpp-mcp", client=None) -> str:
    if not meta.registration_endpoint:
        raise RuntimeError("Instancja BPP nie udostępnia rejestracji (DCR).")
    cli, owns = _client_ctx(client)
    try:
        resp = cli.post(
            meta.registration_endpoint,
            json={"client_name": client_name, "redirect_uris": [redirect_uri]},
        )
        if resp.status_code >= 400:
            tresc = " ".join(resp.text.split())[:300]
            raise RuntimeError(f"Rejestracja klienta odrzucona ({resp.status_code}): {tresc}")
        return resp.json()["client_id"]
    finally:
        if owns:
            cli.close()
```
W `refresh`, tuż po sprawdzeniu `refresh_token`:
```python
    if not ts.client_id:
        raise RefreshFailed("Brak client_id — wymagane ponowne logowanie.")
```
Dodaj testy: `register_client` z 429 → `RuntimeError` z fragmentem ciała;
`register_client` gdy `registration_endpoint is None` → `RuntimeError`.

### [D5] Task 2 — test `_whoami` na błędzie sieci
```python
@respx.mock
def test_whoami_siec_none():
    respx.get(f"{BASE}/api/v1/whoami/").mock(side_effect=httpx.ConnectError("x"))
    assert oauth_client._whoami(BASE, "AT") is None
```

### [W5]+[W9] Task 3 — testy: skip-DCR i payload token-exchange
W `test_login_pelny_flow` przechwyć route tokenu i zasertuj payload:
```python
    token_route = respx.post(f"{BASE}/o/token/").mock(
        return_value=httpx.Response(
            200, json={"access_token": "AT", "refresh_token": "RT", "expires_in": 1800}
        )
    )
    # ... po login():
    body = dict(urllib.parse.parse_qsl(token_route.calls.last.request.content.decode()))
    assert body["grant_type"] == "authorization_code"
    assert body["code"] == "KOD"
    assert body["code_verifier"]           # PKCE verifier, nie challenge
    assert body["redirect_uri"].startswith("http://127.0.0.1:")
```
Nowy test skip-DCR:
```python
@respx.mock
def test_login_existing_client_id_pomija_dcr():
    _meta()
    reg = respx.post(f"{BASE}/o/register/")
    respx.post(f"{BASE}/o/token/").mock(
        return_value=httpx.Response(200, json={"access_token": "AT", "expires_in": 1800})
    )
    respx.get(f"{BASE}/api/v1/whoami/").mock(
        return_value=httpx.Response(200, json={"username": "x"})
    )
    respx.route(host="127.0.0.1").pass_through()
    ts = oauth_client.login(
        BASE, existing_client_id="CID", open_browser=_fake_browser(), timeout=10.0
    )
    assert ts.client_id == "CID"
    assert reg.call_count == 0
```

### [W8] Task 1 — globalna izolacja store w `tests/conftest.py`
Po Task 5 lifespan tworzy `TokenProvider` → `token_store.load()`, więc KAŻDY test
serwera bez izolacji czytałby realny `~/.config`. Dodaj do `tests/conftest.py`:
```python
@pytest.fixture(autouse=True)
def _izolacja_config(tmp_path, monkeypatch):
    """Izoluj token_store od realnego ~/.config w każdym teście."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
```
Per-plikowe fixtury `_izolacja` w test_token_store/test_login_state stają się
redundantne (można zostawić — nieszkodliwe), ale w `test_cli.py` ZACHOWAJ
ustawienie `BPP_BASE_URL`.

### [D-KeyError] Task 6 — `_cmd_login` łapie też `KeyError`
Zdeformowana odpowiedź AS (brak `token_endpoint`/`client_id`/`access_token`) daje
`KeyError`. Rozszerz tuple:
```python
    except (httpx.HTTPError, ValueError, TimeoutError, RuntimeError, KeyError) as exc:
```

### [D1]/[E501] Task 5(e) i Task 6 — zawiń długie linie
Task 5(e) lifespan:
```python
        provider = (
            TokenProvider(config.base_url) if config.transport != "http" else None
        )
```
Task 6 testy — zamiast lambd w `setattr`:
```python
    def _fake(cfg):
        called["login"] = cfg
    monkeypatch.setattr(server, "_cmd_login", _fake)
```
```python
    def _run(*a, **k):
        uruchomiono["run"] = True
    monkeypatch.setattr(server.mcp, "run", _run)
```

### [D2]/[D3] Task 6 — asercje anty-wyciek + ścieżka błędu
W `test_cmd_login_zapisuje_i_drukuje` dodaj: `out = capsys.readouterr().out;
assert "dabrowski" in out; assert "AT" not in out and "RT" not in out`.
Nowy test:
```python
def test_cmd_login_blad_systemexit(monkeypatch):
    def _boom(base_url, *, existing_client_id=None):
        raise TimeoutError("brak callbacku")
    monkeypatch.setattr(server.oauth_client, "login", _boom)
    with pytest.raises(SystemExit):
        server._cmd_login(Config.from_env())
```

### [W6]/[D6] Task 7 — importy na GÓRZE pliku + `pytest.raises`
Nie dopisuj importów na końcu `test_zapytanie.py` (E402). Dodaj brakujące do
istniejącego bloku importów na górze: `from bpp_mcp.client import BppClient` (jeśli
brak), `from bpp_mcp.config import Config`, `from bpp_mcp.auth import
set_current_bearer`. Testy w stylu `pytest.raises`:
```python
@respx.mock
async def test_zapytanie_401_stdio_podpowiada_login():
    cfg = Config(base_url="https://bpp.test", transport="stdio")
    respx.get(url__regex=r".*/zapytanie/rekord/.*").mock(
        return_value=httpx.Response(401, json={"detail": "x"})
    )
    async with BppClient(cfg, backoff_base=0.0) as c:
        with pytest.raises(tools.BppError) as ei:
            await tools.zapytanie_rekord(c, "rok = 2026")
    assert ei.value.status_code == 401
    assert "bpp-mcp login" in str(ei.value)


@respx.mock
async def test_zapytanie_401_http_bez_podpowiedzi_login():
    cfg = Config(base_url="https://bpp.test", transport="http")
    respx.get(url__regex=r".*/zapytanie/rekord/.*").mock(
        return_value=httpx.Response(401, json={"detail": "x"})
    )
    set_current_bearer("DUMMY")  # w http _auth_kwargs wymaga bearera, by dojść do 401
    try:
        async with BppClient(cfg, backoff_base=0.0) as c:
            with pytest.raises(tools.BppError) as ei:
                await tools.zapytanie_rekord(c, "rok = 2026")
        assert ei.value.status_code == 401
        assert "bpp-mcp login" not in str(ei.value)
    finally:
        set_current_bearer(None)
```
(`tools` jest już importowane w `test_zapytanie.py`; `tools.BppError` istnieje —
`tools.py` reeksportuje `BppError` z `client`.)

### [D-mkdir] Task 1 — kosmetyka katalogu pośredniego (opcjonalne)
Można dodać `os.chmod(path.parent.parent, 0o700)` w `save` (guard `OSError`),
by `~/.config/bpp-mcp/` też był 0700. Sekret i tak chroni leaf-dir 0700 + plik
0600 — niski priorytet.
