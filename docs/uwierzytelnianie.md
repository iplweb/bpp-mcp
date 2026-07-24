# Uwierzytelnianie

`bpp-mcp` ma trzy tryby pracy pod względem tożsamości. Domyślnie jest
**anonimowy** (dane publiczne). Aby działać **z uprawnieniami zalogowanego
użytkownika BPP**, wybierz jeden z trybów per-user.

| Tryb | Transport | Kiedy | Logowanie |
|---|---|---|---|
| **Anonimowy** | stdio | dane publiczne, dowolna instancja | brak |
| **Per-user (stdio login)** | stdio | pojedynczy użytkownik, bez hostowania | `bpp-mcp login` (raz) |
| **OAuth (HTTP)** | http | wielu użytkowników, natywny przycisk „authorize" | klient MCP sam prowadzi |

## Tryb anonimowy (domyślny)

Nic nie trzeba robić — narzędzia read-only działają na danych publicznych każdej
instancji API BPP.

## Per-user (logowanie w trybie stdio, bez hostowania)

Domyślny tryb stdio może działać **z uprawnieniami zalogowanego użytkownika** bez
uruchamiania serwera HTTP. Zaloguj się **raz**:

```bash
BPP_BASE_URL=https://bpp.twoja-uczelnia.pl uvx bpp-mcp login
```

Otworzy się przeglądarka na logowanie BPP (hasło/LDAP/Microsoft/ORCID/Keycloak)
i ekran zgody (scope `read`). Po zalogowaniu token trafia do lokalnego pliku
`~/.config/bpp-mcp/<instancja>/tokens.json` (uprawnienia `0600`), a `bpp-mcp`
uruchamiany przez klienta forwarduje go do `/api/v1/` — bez dodatkowych kroków.

!!! tip "Praca zdalna / host bez GUI"
    Adres autoryzacji jest zawsze wypisywany też **tekstem**, więc można go
    otworzyć w przeglądarce na innej maszynie. Callback na `127.0.0.1` wtedy nie
    wróci (przeglądarka jest gdzie indziej) — po zalogowaniu skopiuj z paska
    adresu cały adres przekierowania (zaczyna się od `http://127.0.0.1:`) albo sam
    parametr `code` i wklej w terminalu, gdzie czeka `bpp-mcp login`. Obie drogi —
    loopback i wklejka — działają równolegle; liczy się ta, która dojdzie pierwsza.

!!! note "Gdy instancja nie wystawia `/.well-known/`"
    Logowanie zaczyna się od odczytu metadanych serwera autoryzacji (RFC 8414)
    spod `/.well-known/oauth-authorization-server`. Część wdrożeń blokuje na brzegu
    cały `/.well-known/` (typowo regułą nginksa na pliki ukryte, `location ~ /\.`)
    i oddaje `403`, mimo że serwer autoryzacji działa. `bpp-mcp` cofa się wtedy na
    konwencjonalne ścieżki django-oauth-toolkit (`/o/authorize/`, `/o/token/`,
    `/o/register/`) na tym samym hoście. Właściwą naprawą po stronie serwera jest
    `location ^~ /.well-known/` przed regułą na pliki ukryte — bez tego natywny
    przycisk „authorize" w trybie HTTP nadal nie zadziała (tam discovery robi sam
    klient Claude, nie `bpp-mcp`).

Co odblokowuje:

- **bogatsze wyniki** istniejących narzędzi (rekordy widoczne dla Twojego konta),
- narzędzia **`zapytanie_rekord` / `zapytanie_autor` / `zapytanie_autorzy`**
  (wykonywanie DjangoQL) — wymagają zalogowania i uprawnień redaktora.

Wylogowanie (usuwa token tej instancji):

```bash
BPP_BASE_URL=https://bpp.twoja-uczelnia.pl uvx bpp-mcp logout
```

Token jest krótkotrwały (access ~30 min) i odświeżany po cichu (refresh ~7 dni,
rotujący). Zmiana hasła lub dezaktywacja konta w BPP unieważnia go — wtedy
`bpp-mcp` wraca do trybu anonimowego, a narzędzia `zapytanie_*` poproszą o
ponowne `bpp-mcp login`. Host bierze z `BPP_BASE_URL` (wymagany).

## OAuth (HTTP, per-user, hostowany)

Aby działać z uprawnieniami zalogowanego użytkownika przez serwer HTTP
(OAuth 2.1):

```bash
BPP_BASE_URL=https://bpp.twoja-uczelnia.pl uvx bpp-mcp --http --port 8000
```

Klient MCP (np. Claude) sam przeprowadza logowanie: wykrywa serwer autoryzacji
BPP przez `/.well-known/oauth-protected-resource`, rejestruje się (DCR), otwiera
przeglądarkę na logowanie BPP + ekran zgody (scope `read`), po czym wywołuje
narzędzia z `Bearer`. `bpp-mcp` weryfikuje token przez `GET /api/v1/whoami/` i
forwarduje token **bieżącego requestu** do `/api/v1/`. Zapis jest zablokowany
serwerowo (read-only).

Ten tryb jest wymagany dla klientów przyjmujących **zdalne** serwery MCP przez URL
(np. [ChatGPT](klienci/chatgpt.md)) — serwer musi być osiągalny pod publicznym
adresem HTTPS.

!!! danger "Bezpieczeństwo"
    Trzymaj `--host 127.0.0.1` (domyślnie). Bind na inny host wyłącza wbudowaną
    ochronę DNS-rebinding SDK i eksponuje serwer poza maszynę. Token jest
    forwardowany do API BPP bez wiązania `audience` (świadome odstępstwo od
    MCP-MUST: `bpp-mcp` i API BPP = ta sama domena zaufania; mitygacje: scope
    `read`, twardy read-only serwerowo, krótki TTL).

## Różnica: stdio login vs HTTP

Natywny przycisk „authorize" w Claude (jak przy GitHub) należy do **trybu HTTP** —
wymaga działającego serwera pod URL-em. **Tryb stdio** nie pokazuje tego
przycisku; logowanie przeprowadza komenda `bpp-mcp login`. Oba forwardują token do
tego samego API i wykluczają zapis (read-only serwerowo).
