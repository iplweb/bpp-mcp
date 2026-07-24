# Autodetekcja wdrożenia #21 i self-healing proxy metadanych OAuth

Data: 2026-07-24
Status: design zatwierdzony, przed planem implementacji
Gałąź: `feat-oauth-autodetekcja-proxy`

## Problem

Przycisk „Authorize" w kliencie MCP (Claude Code i pokrewne) pojawia się tylko
dla transportu HTTP, bo klient buduje flow OAuth na podstawie odpowiedzi 401 +
discovery. bpp-mcp ma już w pełni działający tryb HTTP (`--http`, Resource
Server, 157 testów), ale discovery po stronie instancji BPP wymaga, by nginx
przepuścił `/.well-known/`. Poprawka nginxa (bpp-deploy PR #21, zmergowana
2026-07-22) robi to modyfikatorem `location ^~ /.well-known/`, ale jest
wdrażana **stopniowo** — na części instancji `/.well-known/oauth-authorization-server`
nadal zwraca 403 (regexowy `location ~ /\.` przechwytuje żądanie przed aplikacją).

Na takich instancjach klient MCP dostaje 403 przy discovery i „Authorize" pada,
mimo że serwer autoryzacji BPP (`/o/authorize`, `/o/token`, `/o/register`)
działa w pełni poprawnie.

Cel: bpp-mcp ma **sam wykryć**, czy dana instancja ma wdrożony #21, i zachować
się poprawnie w obu przypadkach — bez ręcznego bramkowania rolloutu przez
operatora.

## Kontekst w kodzie (stan przed zmianą)

- `oauth_client.py:60` `discover()` — tryb stdio już wykrywa 403 na
  `.well-known/` i spada na `_konwencjonalne()` (`oauth_client.py:47`), które
  zna ścieżki `/o/authorize/`, `/o/token/`, `/o/register/`. To gotowa
  heurystyka „czy #21 wdrożony", ale używana tylko w stdio.
- `server.py` tryb HTTP: PRM generuje FastMCP z `AuthSettings`, a
  `authorization_servers` w PRM = `issuer_url` = goły `BPP_BASE_URL`. bpp-mcp
  **nie** serwuje własnego `.well-known/oauth-authorization-server`, więc klient
  idzie po metadane wprost do BPP i tam obrywa 403 na niezaktualizowanej
  instancji.
- BPP (`bpp/src/oauth_mcp/`) po odblokowaniu nginxa zwraca kompletne metadane
  RFC 8414 (`views_metadata.py`) oraz DCR + PKCE + `/o/*`. Ten kontrakt PROXY
  kopiuje.

Weryfikacja feasibility (wykonana na żywo): `FastMCP.custom_route` istnieje
(można wystawić własną trasę well-known), `AuthSettings.issuer_url` jest polem,
które kontrolujemy i które ląduje w PRM jako `authorization_servers`.

## Rozwiązanie: dwa tryby wybierane probe'em przy starcie

W trybie `--http` bpp-mcp przy starcie wykonuje **jeden probe** na
`BPP/.well-known/oauth-authorization-server` i ustala tryb na całe życie
procesu:

```
                          ┌─ 200 + poprawny JSON RFC 8414 ─→ PASS-THROUGH
probe BPP/.well-known/ ───┤
                          └─ 403 / HTML / timeout / 5xx ────→ PROXY
```

### PASS-THROUGH (instancja z wdrożonym #21)

- `issuer_url = BPP_root`
- brak własnej trasy well-known
- zachowanie identyczne z dzisiejszym: klient idzie po metadane wprost do BPP
  (ścieżka „błogosławiona", odporna na przyszłe zmiany endpointów w BPP)

### PROXY (instancja bez #21) — tryb domyślny przy niepewności

- `issuer_url = <własny URL bpp-mcp>`
- bpp-mcp rejestruje trasę `/.well-known/oauth-authorization-server`, która
  zwraca dokument RFC 8414 z `issuer = self`, a endpointy → `BPP/o/*`
- Authorize działa NAWET na instancji bez #21

**Decyzja: default PROXY przy niepewności.** Tylko potwierdzone, czyste
200+JSON z wymaganymi polami przełącza w PASS-THROUGH; cokolwiek innego (403,
HTML, 5xx, timeout) → PROXY. Uzasadnienie: PROXY jest poprawny na KAŻDEJ
instancji BPP (wskazuje na realne `/o/*`, które istnieją niezależnie od #21),
więc jest bezpiecznym stanem domyślnym. PASS-THROUGH to jedynie optymalizacja
dla instancji w pełni zgodnej ze standardem.

## Zgodność ze specyfikacją (dlaczego PROXY to nie naginanie)

RFC 8414 §3.3 wymaga, by `issuer` w dokumencie metadanych był identyczny z
adresem, spod którego klient pobrał metadane — czyli z URL-em bpp-mcp. **Nie**
wymaga, by `authorization_endpoint`/`token_endpoint` były na tym samym origin co
issuer; deploye z issuerem i endpointami na różnych domenach są legalne i
powszechne. Ustawiając `issuer = <url bpp-mcp>`, a endpointy na `BPP/o/*`,
pozostajemy zgodni ze specem. Token BPP jest opaque (bez claimu `iss`), więc po
stronie tokenu nie ma czego walidować.

To założenie jest jedynym elementem wymagającym potwierdzenia empirycznego —
patrz „Walidacja empiryczna" niżej.

## Komponenty

Trzy jednostki o pojedynczej odpowiedzialności plus cienkie wpięcie.

### 1. `probe_instance(base_url, *, client) -> AuthMode`

Nowa funkcja w `oauth_client.py`, obok `discover()`. Zwraca `PASSTHROUGH` albo
`PROXY`. Ta sama heurystyka co `discover()`, zwraca *decyzję o trybie*, nie
metadane. Kryterium PASS-THROUGH (identyczne z warunkiem sukcesu `discover()`):
odpowiedź 200, ciało parsuje się jako obiekt JSON i zawiera oba pola
`authorization_endpoint` oraz `token_endpoint`. Brak któregokolwiek warunku →
PROXY. Sieć przez wstrzykiwalny `httpx.Client` (testy bez sieci). Timeout 5 s —
nie blokuje startu, gdy BPP zamula.

`AuthMode` to enum (`PASSTHROUGH` / `PROXY`).

### 2. `authorization_server_metadata(base_url, issuer) -> dict`

Nowa funkcja budująca dokument RFC 8414 dla trybu PROXY:

```json
{
  "issuer": "<url bpp-mcp>",
  "authorization_endpoint": "<base_url>/o/authorize/",
  "token_endpoint": "<base_url>/o/token/",
  "registration_endpoint": "<base_url>/o/register/",
  "revocation_endpoint": "<base_url>/o/revoke_token/",
  "scopes_supported": ["read"],
  "response_types_supported": ["code"],
  "grant_types_supported": ["authorization_code", "refresh_token"],
  "code_challenge_methods_supported": ["S256"],
  "token_endpoint_auth_methods_supported": ["none"]
}
```

Świadomie kopiuje kontrakt z `bpp/src/oauth_mcp/views_metadata.py` — te same
pola, żeby PROXY i PASS-THROUGH dawały klientowi identyczny obraz serwera
autoryzacji. Ścieżki `/o/*` budowane są tą samą konwencją co
`_konwencjonalne()` (`authorize`/`token`/`register`), rozszerzoną o
`revoke_token/` — którego `_konwencjonalne()` nie zawiera, bo stdio go nie
potrzebuje. Rozważyć rozszerzenie `_konwencjonalne()` o revoke i wspólne
źródło ścieżek, by uniknąć dwóch list `/o/*`.

### 3. Wpięcie w `server.py`

- `_auth_kwargs(config, mode)` — dostaje tryb i ustawia `issuer_url` = BPP
  (PASS-THROUGH) albo self (PROXY).
- `build_mcp(config)` — w PROXY rejestruje
  `@mcp.custom_route("/.well-known/oauth-authorization-server")` zwracającą
  `authorization_server_metadata(...)`; w PASS-THROUGH nie rejestruje niczego.
- Probe wywoływany raz w ścieżce startu HTTP (`main()` przy `--http`), wynik
  wstrzykiwany do `build_mcp`.

### Nowy config: URL issuera

W PROXY `issuer` musi równać się adresowi, spod którego klient pobiera
well-known bpp-mcp. Wyprowadzany z tego samego źródła co
`effective_resource_url` (dziś `http://host:port/mcp`): issuer = ten URL bez
sufiksu `/mcp`. Dla wdrożeń za reverse-proxy istnieje już
`BPP_MCP_RESOURCE_URL`; dokładamy spójny, opcjonalny `BPP_MCP_ISSUER_URL` jako
nadpisanie (domyślnie wyprowadzany z resource_url).

## Obsługa błędów

- Probe: jedyny wynik dający PASS-THROUGH to czyste 200 + poprawny JSON RFC 8414
  z wymaganymi polami. 403 / HTML / 5xx / timeout / błąd sieci → PROXY.
- Timeout probe'a: 5 s, nie blokuje startu.
- PROXY jest bezpiecznym stanem końcowym także wtedy, gdy BPP jest chwilowo
  nieosiągalne przy starcie — endpointy `/o/*` i tak są znane z konwencji, a
  ewentualny błędny strzał zmaterializuje się jako czytelny błąd na `/o/token/`,
  nie jako ciche milczenie.

## Testy

Wzorem istniejącego `tests/test_http_auth.py`:

- `probe_instance`: 200+JSON → PASSTHROUGH; 403 → PROXY; 200+HTML → PROXY;
  timeout → PROXY; 5xx → PROXY.
- `authorization_server_metadata`: `issuer` = self, endpointy = `/o/*`, komplet
  wymaganych pól.
- integracyjny PROXY: `GET /.well-known/oauth-authorization-server` → 200,
  `issuer` = self; PRM `authorization_servers` = [self].
- integracyjny PASS-THROUGH: ta trasa → 404; PRM `authorization_servers` =
  [BPP].

## Walidacja empiryczna (PIERWSZY krok implementacji)

Zanim napiszemy testy i pełne wpięcie: minimalny spike (proxy zahardkodowany),
podpiąć realny Claude Code jako connector HTTP przeciw NIEZMIENIONEJ instancji
`publikacje.up.lublin.pl` (403 na discovery), kliknąć Authorize i potwierdzić,
że łańcuch discovery → DCR → authorize → token → whoami przechodzi end-to-end.

Uzasadnienie: cała wartość funkcji stoi na założeniu, że klient akceptuje split
issuer/endpoint. Analiza speca mówi, że tak; spike to potwierdza jednym klikiem,
zanim wydamy czas na testy i wpięcie. Jeśli spike padnie — wracamy do stołu z
kosztem 15 minut, nie kilku dni.

## Poza zakresem (YAGNI)

- Detekcja na żywo / periodyczna / z cache — świadomie odrzucona. Stan instancji
  zmienia się raz (moment deployu); restart procesu bpp-mcp po wdrożeniu #21 na
  daną instancję jest akceptowalny i deterministyczny.
- Introspekcja tokenu (RFC 7662) — poza zakresem, weryfikacja przez whoami bez
  zmian.
- Zmiany w samym BPP i bpp-deploy — ten spec dotyczy wyłącznie bpp-mcp.
