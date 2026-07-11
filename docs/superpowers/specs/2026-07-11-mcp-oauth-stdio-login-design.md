# bpp-mcp: logowanie OAuth 2.1 w trybie stdio (self-authorizing client) — spec

**Data:** 2026-07-11
**Repo:** `iplweb/bpp-mcp`
**Status:** zatwierdzony (brainstorming → writing-plans)

## 1. Cel

Umożliwić użytkownikowi **zalogowanie się do BPP** przez `bpp-mcp` uruchomiony
w **domyślnym trybie stdio** (Claude sam odpala serwer), bez hostowania i bez
trzymania działającego procesu HTTP. Po jednorazowym `bpp-mcp login`
(przeglądarka + zgoda BPP) serwer forwarduje token zalogowanego użytkownika do
`/api/v1/`, dając bogatsze wyniki istniejących narzędzi oraz dostęp do narzędzi
`zapytanie_*` (DjangoQL), które wymagają zalogowania.

To **Droga A** z rozmowy projektowej. **Droga B** (transport HTTP + Resource
Server, natywny przycisk „authorize" w Claude) jest już zaimplementowana
(PR #1) i pozostaje osobną, komplementarną ścieżką (hostowaną). Ten spec jej
nie zmienia.

## 2. Zakres i nie-zakres

**W zakresie:**
- OAuth 2.1 **native-app flow** (RFC 8252) po stronie `bpp-mcp` jako **public
  client + PKCE** (loopback redirect).
- Trwały, per-instancja cache tokenów (`~/.config/bpp-mcp/…`, chmod 600).
- Podkomendy CLI: `bpp-mcp login`, `bpp-mcp logout`.
- Wpięcie tokenu ze store w istniejącą ścieżkę forwardowania Bearera w trybie
  stdio (ContextVar + `BppClient`).
- Cichy refresh access-tokenu (z rotacją refresh-tokenu) przy wygaśnięciu.
- **Hybryda** przy braku tokenu: narzędzia anonimowe działają jak dziś;
  narzędzia `zapytanie_*` zwracają czytelną instrukcję „uruchom `bpp-mcp login`".

**Poza zakresem (YAGNI / osobno):**
- Jakiekolwiek zmiany po stronie BPP — Authorization Server (`oauth_mcp`) na
  `dev` ma już DCR (public client), PKCE, loopback allowlist, AS-metadata,
  rotujący refresh. **Zero zmian w BPP.**
- Tryb HTTP / Resource Server (PR #1) — bez zmian.
- Nowe narzędzia poza istniejącymi — `zapytanie_{rekord,autor,autorzy}` już są
  na `main` (PR #2). Raporty slotów: możliwy późniejszy follow-up.
- Automatyczny „login w locie" przy wywołaniu narzędzia (odrzucony: ryzyko
  timeoutów MCP przy blokowaniu wywołania na czas ludzkiego logowania).

## 3. Kontrakt Authorization Servera BPP (zweryfikowany z `origin/dev`)

- **AS-metadata (RFC 8414):** `GET {base}/.well-known/oauth-authorization-server`
  → `authorization_endpoint` (`/o/authorize/`), `token_endpoint` (`/o/token/`),
  `registration_endpoint` (`/o/register/`), `revocation_endpoint`,
  `code_challenge_methods_supported: ["S256"]`, `scopes_supported: ["read"]`,
  `token_endpoint_auth_methods_supported: ["none"]`.
- **DCR (RFC 7591):** `POST {registration_endpoint}` z
  `{"client_name": …, "redirect_uris": [...]}`. Allowlista redirectów zawiera
  `http://127.0.0.1(:port)/…` i `http://localhost(:port)/…` (loopback OK).
  Zwraca `client_id`, `token_endpoint_auth_method: "none"` (public), rate-limit
  20/h/IP. **Bez** client_secret.
- **Authorize:** `GET {authorization_endpoint}?response_type=code&client_id=…&
  redirect_uri=…&scope=read&state=…&code_challenge=…&code_challenge_method=S256`.
  Krok zgody loguje wszystkimi metodami BPP (hasło/LDAP/Microsoft/ORCID/Keycloak).
- **Token:** `POST {token_endpoint}` (public, `code_verifier`) →
  `access_token`, `refresh_token`, `expires_in` (access 30 min).
- **Refresh:** `grant_type=refresh_token` → nowy access **ORAZ nowy refresh**
  (`ROTATE_REFRESH_TOKEN=True`, refresh żyje 7 dni). Rotowany refresh **trzeba
  zapisać**, inaczej kolejny refresh padnie.
- **Tożsamość:** `GET {base}/api/v1/whoami/` z Bearerem → `{id, username, …}`.
- **Egzekucja API:** globalny DRF `StrictOAuth2Authentication` → każdy
  `/api/v1/` rozumie Bearera; jawny zły Bearer = twardy 401 (nie degraduje do
  anona).

## 4. Architektura i moduły

Tryb stdio zyskuje **opcjonalną tożsamość**: obecny token w store → forward;
brak → anonimowo (jak dziś). Login to osobna, jednorazowa komenda CLI.

### Nowe moduły (`src/bpp_mcp/`)

**`token_store.py`** — trwałość tokenów. Bez sieci.
```python
@dataclass
class TokenSet:
    base_url: str
    access_token: str
    refresh_token: str | None
    expires_at: float          # epoch seconds (now + expires_in przy zapisie)
    token_endpoint: str        # zapisany, by refresh nie robił discovery
    username: str | None
    client_id: str | None
    def is_expired(self, skew: float = 60.0, *, now: float | None = None) -> bool: ...

def store_path(base_url: str) -> Path: ...   # ~/.config/bpp-mcp/<sha256(base)[:16]>/tokens.json
def load(base_url: str) -> TokenSet | None:  # None gdy brak/uszkodzony/niekompletny
def save(ts: TokenSet) -> None:              # mkdir 0700, temp+os.replace, chmod 0600
def clear(base_url: str) -> None:            # logout; idempotentny
```
- Katalog `~/.config` respektuje `$XDG_CONFIG_HOME`.
- Klucz per-instancja = `sha256(base_url)[:16]` — umlub ≠ inna uczelnia = osobne
  pliki, żadnego mieszania tożsamości.
- Zapis **atomowy** (temp w tym samym katalogu + `os.replace`); plik nigdy nie
  jest półzapisany ani chwilowo world-readable.
- `load` toleruje uszkodzenie: brak pliku / zły JSON / brak wymaganego pola →
  `None` (traktowane jak „niezalogowany"), nie wysypuje serwera.

**`oauth_client.py`** — native-app flow (RFC 8252). Sieć przez `httpx`,
przeglądarka `webbrowser`, loopback `http.server`, PKCE `secrets`+`hashlib`.
```python
@dataclass
class Metadata:
    authorization_endpoint: str
    token_endpoint: str
    registration_endpoint: str | None

def discover(base_url: str, *, http=httpx) -> Metadata: ...
def register_client(meta, redirect_uri, *, client_name="bpp-mcp") -> str: ...  # client_id
def login(base_url, *, existing_client_id: str | None = None,
          timeout: float = 300.0) -> TokenSet: ...     # pełny flow (interaktywny)
def refresh(ts: TokenSet, *, http=httpx) -> TokenSet: ...  # zwraca NOWY TokenSet (rotacja)
```
- Funkcje są małe i osobno testowalne; `login` skleja kroki (patrz §5).
- Loopback: `HTTPServer` na `127.0.0.1:0` (system daje wolny port), jeden
  handler łapie `GET /callback?code&state`, oddaje stronę „Zalogowano — wróć do
  Claude", przekazuje `code` przez `queue.Queue`. Timeout 300 s. `state`
  walidowany (mismatch → wyjątek, bez wymiany kodu).
- Sieć wstrzykiwalna (`http=` / injekcja klienta) — testy respx bez realnych
  wywołań; loopback testowany przez bezpośrednie wywołanie handlera.

**`login_state.py`** — provider tokenu dla żądań stdio (async).
```python
class TokenProvider:
    def __init__(self, config, *, refresh_fn=oauth_client.refresh): ...
    async def bearer(self) -> str | None:
        # 1) load ze store (raz, potem w pamięci); brak → None
        # 2) ważny → access_token
        # 3) wygasły + refresh → refresh_fn (pod asyncio.Lock), save(nowy), zwróć
        # 4) refresh padł (invalid_grant/401) → clear store, None (+ log stderr)
```
- `asyncio.Lock` serializuje refresh: pierwszy odświeża i zapisuje, reszta
  czeka i czyta świeży token (rotujący refresh znosi podwójne użycie — bez locka
  dwa równoległe refreshe wzajemnie unieważniłyby refresh_token).
- Trzyma bieżący `TokenSet` w pamięci; store czyta raz na starcie i po każdym
  zapisie zostaje spójny.

### Zmieniane (istniejące)

**`server.py`:**
- `KontekstApp` dostaje pole `bearer_provider: TokenProvider | None`.
- `lifespan` (domknięcie nad `config`): w stdio buduje `TokenProvider(config)`;
  w http `None`.
- `_client(ctx)` staje się **async**; kolejność bearera: request-bearer
  (`bearer_from_request`) **or** `await bearer_provider.bearer()` (stdio) →
  `set_current_bearer(...)`. **10** wrapperów wołających `_client` dostaje `await
  _client(ctx)` (wszystkie prócz `djangoql_schema`, które jest lokalne i nie
  dotyka `ctx`/klienta).
- `main()`: podkomendy `login` / `logout` obok domyślnego serwera (`--http`
  jak dziś).

**`tools.py`:** narzędzia `zapytanie_*` — przy 401/403 **bez tokenu w store**
wzbogacają komunikat o instrukcję „uruchom `bpp-mcp login`" (hybryda). Gdy token
jest, 401/403 zostają jak dziś (nieaktywne konto / brak uprawnień).

**`config.py`, `client.py`:** bez zmian w passthrough — Bearer już wygrywa w
`_auth_kwargs`; stdio+token tylko *dostarcza* bearer tą samą rurą.

## 5. Przepływ `login`

`bpp-mcp login` (host z `BPP_BASE_URL`; domyślnie umlub):

1. **Discovery** — `GET {base}/.well-known/oauth-authorization-server`.
2. **Loopback** — start `HTTPServer` na `127.0.0.1:0`; `redirect_uri =
   http://127.0.0.1:<port>/callback`.
3. **DCR (raz)** — jeśli store nie ma `client_id` dla tej instancji:
   `POST {registration_endpoint}` z tym `redirect_uri` → `client_id`
   (zapamiętany w store; kolejne logowania reużywają).
4. **PKCE + state** — `verifier=token_urlsafe(64)`,
   `challenge=b64url(sha256(verifier))`, `state=token_urlsafe(32)`.
5. **Authorize** — `webbrowser.open(authorization_endpoint?…)`. User loguje się
   w BPP + zgoda (scope `read`).
6. **Callback** — czekaj (timeout 300 s) na `GET /callback?code&state`; waliduj
   `state`; zamknij listener.
7. **Token exchange** — `POST {token_endpoint}` (public, `code_verifier`) →
   access/refresh/expires_in.
8. **whoami** — `GET {base}/api/v1/whoami/` → `username` (miękkie: błąd nie
   wywraca loginu, `username=None`).
9. **Zapis** — `token_store.save(TokenSet(...))`; wypisz „Zalogowano jako
   {username} @ {base}".

`bpp-mcp logout`: `token_store.clear(base)` + komunikat.

## 6. Obsługa błędów

| Sytuacja | Zachowanie |
|---|---|
| `login`: user zamknął przeglądarkę / brak callbacku | timeout 300 s → czytelny błąd CLI, kod ≠ 0, listener zamknięty |
| `login`: `state` mismatch | wyjątek, BEZ wymiany kodu (ochrona CSRF) |
| `login`: DCR odmówił (rate-limit/redirect) | komunikat z treścią błędu AS |
| `login`: AS/token endpoint 4xx/5xx | czytelny błąd CLI (bez tracebacku) |
| Serwer stdio: token ważny | forward Bearera |
| Serwer stdio: access wygasł, refresh OK | cichy refresh (pod locakiem) + save |
| Serwer stdio: refresh padł (hasło zmienione / rewokacja) | `clear` store, tryb anon, log na stderr |
| `zapytanie_*` bez tokenu (401/403, brak store) | komunikat: „Nie jesteś zalogowany — uruchom `bpp-mcp login`" |
| `zapytanie_*` z tokenem, 403 | jak dziś (brak uprawnień redaktora) |
| store uszkodzony | `load`→None (anon), serwer żyje |

Zero bare `except`: wąskie typy (`httpx.HTTPError`, `json.JSONDecodeError`,
`OSError`, `KeyError`), każdy z sensownym komunikatem lub re-raise.

## 7. Bezpieczeństwo

- **Public client + PKCE** — brak sekretu do wycieku; ochrona kodu przez S256.
- **Loopback** na `127.0.0.1` (nie `0.0.0.0`); port ulotny; listener żyje tylko
  na czas jednego logowania.
- **`state`** waliduje CSRF; **PKCE** wiąże żądanie autoryzacji z wymianą tokenu.
- **Token at rest**: plik `0600`, katalog `0700`, zapis atomowy. To standard
  (jak `~/.ssh`, `gh`, `gcloud`). Access krótki (30 min), refresh rotujący (7
  dni), rewokowany przy zmianie hasła/dezaktywacji konta po stronie BPP.
- **Per-instancja** — token jednej uczelni nie trafi do żądania innej.
- Zawartości tokenów nie logujemy (ani do stderr, ani do plików poza store).

## 8. Testy (offline, `respx`)

- **`token_store`**: ścieżka/hash per-instancja; `save` tworzy 0700/0600 i jest
  atomowy; `load` round-trip; `load` na uszkodzonym/niekompletnym → None;
  `clear` idempotentny; `is_expired` ze wstrzykniętym `now`.
- **`oauth_client`**: `discover` parsuje metadata; `register_client` wysyła
  poprawny payload i zwraca `client_id`; PKCE `challenge==b64url(sha256(verifier))`;
  `login` — flow z zamockowanym callbackiem (handler wywołany bezpośrednio z
  `code`+`state`), zły `state` → wyjątek; `refresh` zwraca NOWY TokenSet z
  rotowanym refresh; błędy 4xx/5xx → czytelny wyjątek.
- **`login_state.TokenProvider`**: ważny token → bearer; wygasły → refresh+save
  wywołane raz mimo równoległych `bearer()` (lock); refresh invalid_grant →
  clear + None.
- **Wpięcie stdio**: `_client(ctx)` bez request-bearera ustawia bearer z
  providera; z request-bearerem (http) provider ignorowany; brak providera →
  None.
- **`zapytanie_*` hybryda**: 401/403 bez store → komunikat z „`bpp-mcp login`";
  z tokenem → komunikat bez tej podpowiedzi.
- **CLI**: `bpp-mcp login` woła flow i `save`; `bpp-mcp logout` woła `clear`;
  brak podkomendy → serwer (jak dziś).
- **Regresja**: pełny zestaw dotychczasowy zielony; `ruff check` + `ruff format
  --check` czyste; `pre-commit run --all-files` Passed.

## 9. Dokumentacja

README: sekcja „Logowanie (stdio, per-user)" — `bpp-mcp login` / `logout`, co
odblokowuje (bogatsze wyniki + `zapytanie_*`), gdzie leży token (i że to plik
0600), oraz jasne rozróżnienie od trybu HTTP (natywny „authorize" — Droga B).
Newsfragment (jeśli repo używa) / wpis do changelogu.
