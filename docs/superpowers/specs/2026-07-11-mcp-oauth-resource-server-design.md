# bpp-mcp jako OAuth 2.1 Resource Server — spec §6

**Data:** 2026-07-11
**Repo:** `iplweb/bpp-mcp`
**Status:** design (do review usera)
**Powiązany spec (strona BPP, §5):** `bpp` repo, gałąź `dev` (scalone) —
`docs/superpowers/specs/2026-07-11-mcp-oauth-authorization-design.md`. Tamten
dostarcza Authorization Server + token-aware API. Ten dokument realizuje **§6 —
stronę Resource Server** i jest wobec tamtego konsumentem („producent przed
konsumentem").

---

## 1. Cel

Umożliwić serwerowi MCP `bpp-mcp` działanie **z uprawnieniami konkretnego,
zalogowanego użytkownika BPP** przez OAuth 2.1 — zamiast wyłącznie anonimowego
API. `bpp-mcp` pełni rolę **Resource Servera**: waliduje token przedstawiony
przez klienta MCP (Claude) i forwarduje go do `/api/v1/`. `bpp-mcp` **nigdy** nie
trzyma haseł ani nie prowadzi browser-flow — to robi klient.

**MVP: read-only.** Egzekwowane serwerowo przez BPP (middleware `/api/v1/`),
`bpp-mcp` i tak eksponuje wyłącznie narzędzia czytające.

## 2. Decyzje (zatwierdzone w brainstormingu)

1. **Transport: Streamable HTTP na localhost.** OAuth w MCP to feature
   transportu HTTP (discovery dance: 401 → protected-resource-metadata →
   AS metadata → DCR → authorize). Tryb **stdio (anonimowy) zostaje bez zmian**
   — kompatybilność wstecz; OAuth to nowa, oddzielna ścieżka HTTP.
2. **Zakres: wyłącznie OAuth / Resource Server.** Odłożone tematy
   (`bibliometria_autora`, hardening `szukaj_autora`) — osobny spec/PR później.
3. **Weryfikacja tokenu: wbudowany OAuth RS FastMCP + własny `WhoamiTokenVerifier`.**
   Token BPP jest **opaque** (nie JWT) → weryfikacja tylko zdalnie, przez
   `GET /api/v1/whoami/`. Introspekcja odrzucona dla MVP (wymaga confidential
   clienta; endpoint w BPP nieaktywny).

## 3. Kontrakt BPP (wyekstrahowany z kodu `dev`)

Wszystko względem `BPP_BASE_URL` (np. `https://bpp.umlub.pl`); issuer = **root**
(bez `/o`).

| Rola | Endpoint |
|---|---|
| AS metadata (RFC 8414) | `GET /.well-known/oauth-authorization-server` |
| Authorize (PKCE **S256 wymagane**, scope `read`) | `/o/authorize/` |
| Token | `/o/token/` |
| Revoke | `/o/revoke_token/` |
| Dynamic Client Registration (RFC 7591) | `POST /o/register/` |
| Preflight tożsamości | `GET /api/v1/whoami/` |
| Dane | `GET /api/v1/...` z `Bearer` |

Właściwości: **public client, PKCE S256, bez sekretu, token opaque**, jedyny
scope `read`, krótki TTL + rotacja refresh, **write przez token → 403**
(egzekwowane serwerowo). DCR **dopuszcza** `http://localhost:*` /
`http://127.0.0.1:*` (allowlista) — kluczowe dla wariantu localhost.

Kształt `whoami` (200): `{"id", "username", "is_staff", "is_superuser"}`.
Brak/nieważny token → **HTTP 401**.

## 4. Architektura i komponenty

`bpp-mcp` jako Resource Server na Streamable HTTP (localhost). Komponenty —
małe, testowalne jednostki:

| Jednostka | Odpowiedzialność | Zależności |
|---|---|---|
| `auth.py` → `WhoamiTokenVerifier` | implementuje `TokenVerifier` SDK: `verify_token(opaque)` → `GET {BPP}/api/v1/whoami/` z `Bearer`; 200 → obiekt tokenu z tożsamością (`username`, `id`, scope `read`); 401 → `None`; 5xx/timeout → wyjątek | httpx, config |
| `auth.py` → bridge `contextvar` | `set/get_current_bearer` — most między warstwą auth a `BppClient`; unika przewlekania tokenu przez wszystkie narzędzia | — |
| `auth.py` → positive-cache | krótki (≈30 s) cache wyniku `whoami` per token; redukuje +1 request/wywołanie i wygładza blipy sieciowe | — |
| `config.py` (rozszerzenie) | `BPP_BASE_URL` (API **i** issuer AS), `BPP_MCP_TRANSPORT`, `BPP_MCP_HTTP_HOST/PORT`, `BPP_MCP_RESOURCE_URL`; zachowuje `BPP_BASIC_AUTH` | os.environ |
| `client.py` (`BppClient`) | per-request wstrzyknięcie `Authorization: Bearer` z contextvar (gdy jest); brak → Basic/anon jak dziś | httpx |
| `server.py` | w trybie HTTP montuje FastMCP z `auth=WhoamiTokenVerifier`; nowy entrypoint HTTP; **PRM i 401+WWW-Authenticate serwuje sam FastMCP** | mcp SDK |

**Kluczowa elegancja:** `WhoamiTokenVerifier` **jest** preflightem. FastMCP woła
`verify_token` na każdym żądaniu transportu → token wygasły/zrewokowany → `None`
→ SDK zwraca transportowy 401 → klient re-autoryzuje. Nie ma potrzeby osobnego
preflightu ani łapania 401 w środku tool-calla (ból ze spec §5.4d znika, bo
weryfikacja żyje w warstwie transportu, nie w JSON-RPC).

## 5. Flow end-to-end

1. Claude → `bpp-mcp` (HTTP) bez tokenu → **401 + `WWW-Authenticate: Bearer
   resource_metadata="…/.well-known/oauth-protected-resource"`**.
2. Claude: PRM (`authorization_servers:[BPP_BASE_URL]`) → AS metadata BPP →
   **DCR** `/o/register/` → `client_id` (localhost redirect na allowliście DCR).
3. Claude → przeglądarka → `/o/authorize/` (PKCE S256, scope `read`) →
   logowanie BPP → ekran zgody → `code`.
4. `code` → `/o/token/` → **access token** (+ rotujący refresh).
5. Claude ponawia żądania MCP z `Bearer`; `WhoamiTokenVerifier` waliduje przez
   `whoami`; `BppClient` forwarduje `Bearer` do `/api/v1/`.
6. Token wygasa → następny `verify_token` → `whoami` 401 → transportowy 401 →
   cichy refresh/re-auth po stronie klienta.

## 6. Błędy i re-auth

- **Brak/nieważny/wygasły/zrewokowany token** → `verify_token` → `None` →
  transportowy 401 + `WWW-Authenticate`.
- **Rozróżnienie „nieważny" vs „BPP niedostępne":** `whoami` 401 → `None`
  (re-auth). `whoami` 5xx/timeout → **wyjątek → 502/503**, NIE `None` (bez
  zbędnego re-authu przy chwilowej awarii BPP).
- **Positive-cache** (≈30 s): trade-off — TTL = maksymalne opóźnienie, zanim
  zrewokowany token przestanie działać (akceptowalne przy krótkim TTL tokenu).
- **401 z `/api/v1/` w środku tool-calla** (token zrewokowany między verify a
  wywołaniem — rzadkie): `BppClient` mapuje na błąd narzędzia; następne żądanie
  i tak re-weryfikuje (401 na transporcie).
- **Write (non-SAFE) → 403 z BPP:** w praktyce N/A (tylko narzędzia czytające);
  gdyby forwardowane — 403 jako błąd narzędzia.

## 7. Config i współistnienie

Precedencja auth per request: **`Bearer` (OAuth, per-user) > `BPP_BASIC_AUTH`
(serwisowy) > anonimowo.** W trybie stdio: Basic albo anonimowo (bez OAuth).

Zmienne środowiskowe:
- `BPP_BASE_URL` — API **i** issuer AS (istnieje).
- `BPP_MCP_TRANSPORT` — `stdio` (**domyślnie**, kompat) | `http`.
- `BPP_MCP_HTTP_HOST` — default `127.0.0.1`.
- `BPP_MCP_HTTP_PORT` — port HTTP.
- `BPP_MCP_RESOURCE_URL` — default `http://127.0.0.1:<port>`; pole `resource`
  w PRM.
- `BPP_BASIC_AUTH` — zachowany (raporty slotów, ścieżka serwisowa).

Entrypoint: `bpp-mcp` bez flag → stdio (jak dziś); `bpp-mcp --http --port N` →
Streamable HTTP + OAuth.

## 8. Bezpieczeństwo

- **Read-only** egzekwowane serwerowo (BPP middleware); `bpp-mcp` ma tylko
  narzędzia czytające.
- **Nieważny bearer → transportowy 401**, nie cicha degradacja do anona
  (naturalne z `TokenVerifier`).
- **Token passthrough — świadome, udokumentowane odstępstwo od MCP MUST (spec
  §8/W3):** token opaque bez `aud` (RFC 8707 niewspierane przez DOT). `bpp-mcp`
  i API BPP = ta sama domena zaufania (IPLWEB). Mitygacje: jedyny scope `read`,
  twardy read-only serwerowo, krótki TTL. Ryzyko rezydualne: dowolny token AS
  BPP będzie honorowany przez oba.
- **Bind do localhost** (`127.0.0.1`) — brak ekspozycji sieciowej.
- Cache tokenów w pamięci procesu (nie na dysk); TTL krótki.

## 9. Wielo-instancyjność

`BPP_BASE_URL` odkrywa AS i API danej instancji; DCR i tokeny per-instancja
(klient rejestruje się osobno na każdą instancję). Issuer budowany po stronie
BPP z `request` (wielo-domenowość) — `bpp-mcp` konsumuje `authorization_servers`
z PRM/AS-metadata, nie hardkoduje.

## 10. Testy

respx/httpx mock + FastMCP in-memory:
- `verify_token`: `whoami` 200 → ważny (tożsamość + scope `read`); 401 → `None`;
  5xx/timeout → wyjątek (nie `None`).
- Transport: żądanie bez `Bearer` → 401 + kształt `WWW-Authenticate`.
- **PRM**: kształt dokumentu (`resource`, `authorization_servers=[BPP_BASE_URL]`).
- **Passthrough**: uwierzytelnione wywołanie narzędzia → `BppClient` wysyła
  `Authorization: Bearer` do zamockowanego `/api/v1/`; anonimowe stdio → brak
  nagłówka `Authorization`.
- **Precedencja**: `Bearer` obecny → `Basic` ignorowany; brak `Bearer` +
  `Basic` ustawiony → `Basic` użyty.
- **Cache**: 2 wywołania w TTL → 1 hit `whoami`; po TTL → re-weryfikacja.
- **Regres**: istniejące anonimowe narzędzia w stdio bez zmian.
- **Smoke (opcjonalny, manualny):** pełny dance OAuth wobec żywej instancji.

## 11. Zależności / ryzyka implementacyjne

- **Wersja SDK:** `mcp[cli]>=1.2.0` jest za stare na abstrakcję `TokenVerifier`
  / OAuth RS. **Bump do wersji z RS-auth** (albo przejście na standalone
  `fastmcp` 2.x z `RemoteAuthProvider`/`TokenVerifier`) — do przypięcia w planie
  implementacji. Fallback (gdyby `TokenVerifier` nie żenił się z
  opaque+whoami): ręczna warstwa ASGI (Wariant 2 z brainstormingu).
- **Kształt PRM/WWW-Authenticate** musi być zgodny z tym, czego oczekuje klient
  MCP (Claude) — zweryfikować wobec aktualnej wersji MCP auth spec.

## 12. Poza zakresem

- `bibliometria_autora`, hardening `szukaj_autora` — osobny spec/PR.
- Introspekcja / confidential client (RFC 7662), audience binding (RFC 8707).
- Zapis/import przez API (write).
- Hosting zdalny (remote connector) — wariant lokalny (localhost) w MVP.

## 13. Otwarte pytania (do rozstrzygnięcia w planie, z rekomendacją)

- Dokładna wersja `mcp`/`fastmcp` z `TokenVerifier` i kształt API auth-providera
  — **rekomendacja:** przypiąć podczas planu po weryfikacji changelogu SDK;
  preferować `mcp[cli]` (mniej zależności), przejść na standalone `fastmcp` 2.x
  tylko jeśli `mcp[cli]` nie eksponuje `TokenVerifier`.
- Positive-cache: **rekomendacja — per-proces globalny** (prosty, współdzielony
  między połączeniami; klucz = token).
- `bpp-mcp --http` — serwer tylko czeka na klienta; browser-flow inicjuje klient
  MCP, nie serwer (rozstrzygnięte).
