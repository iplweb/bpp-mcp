# bpp-mcp

[![tests](https://github.com/iplweb/bpp-mcp/actions/workflows/tests.yml/badge.svg)](https://github.com/iplweb/bpp-mcp/actions/workflows/tests.yml)

Serwer [MCP](https://modelcontextprotocol.io) dla **API BPP** (Bibliografia
Publikacji Pracowników). Wystawia read-only, anonimowe API BPP (`/api/v1/`)
jako zestaw kuratorowanych, typowanych narzędzi dla Claude Desktop, Claude
Code i innych klientów MCP.

Zamiast żmudnego chodzenia po hyperlinkach REST-owych (publikacja → autorzy →
jednostka → …), serwer robi to za agenta: rozwija relacje, auto-follow-uje
paginację i zwraca gotowe, zagnieżdżone obiekty.

## Dlaczego MCP, a nie samo API?

API BPP jest **hyperlinked** — relacje to URL-e, nie zagnieżdżone dane.
Pobranie jednego rekordu z autorami i źródłem to kilka–kilkanaście żądań.
`bpp-mcp` ukrywa tę złożoność: `pobierz_rekord` zwraca jeden obiekt z
rozwiniętymi autorami (nazwisko jak wydrukowane), źródłem i streszczeniami.

## Konfiguracja

Serwer jest wielo-instancyjny — tę samą binarkę podłączasz do dowolnego
wdrożenia BPP przez zmienne środowiskowe:

| Zmienna | Domyślnie | Opis |
|---|---|---|
| `BPP_BASE_URL` | **wymagany** | bazowy URL instancji BPP (API i issuer OAuth) |
| `BPP_BASIC_AUTH` | *(brak)* | opcjonalny `user:pass` (tylko raporty slotów, stdio) |
| `BPP_MCP_TRANSPORT` | `stdio` | `stdio` (anon) lub `http` (OAuth per-user) |
| `BPP_MCP_HTTP_HOST` | `127.0.0.1` | bind serwera HTTP (tryb `http`) |
| `BPP_MCP_HTTP_PORT` | `8000` | port serwera HTTP (tryb `http`) |
| `BPP_MCP_RESOURCE_URL` | `http://<host>:<port>/mcp` | pole `resource` w protected-resource-metadata |

## Instalacja i uruchomienie

Najprościej, bezpośrednio z gita przez [uv](https://docs.astral.sh/uv/):

```bash
BPP_BASE_URL=https://bpp.twoja-uczelnia.pl \
  uvx --from git+https://github.com/iplweb/bpp-mcp bpp-mcp
```

Albo instalacja pip z gita:

```bash
pip install "git+https://github.com/iplweb/bpp-mcp"
BPP_BASE_URL=https://bpp.twoja-uczelnia.pl bpp-mcp
```

`BPP_BASE_URL` jest **wymagany i nie ma wartości domyślnej** — bez niego serwer
nie wystartuje, tylko wypisze, czego brakuje. To celowe: każde wdrożenie BPP to
inna uczelnia i inna bibliografia, więc zaszyty host oznaczałby, że użytkownik
bez tej zmiennej dostaje cudze dane wyglądające na własne.

Serwer komunikuje się po stdio (standard MCP) — normalnie uruchamia go klient
MCP, nie użytkownik ręcznie.

### Tryb OAuth (HTTP, per-user)

Domyślnie `bpp-mcp` działa po **stdio** i anonimowo (dane publiczne). Aby działać
**z uprawnieniami zalogowanego użytkownika BPP** (OAuth 2.1):

```bash
BPP_BASE_URL=https://bpp.twoja-uczelnia.pl uv run bpp-mcp --http --port 8000
```

Klient MCP (Claude) sam przeprowadza logowanie: wykrywa serwer autoryzacji BPP
przez `/.well-known/oauth-protected-resource`, rejestruje się (DCR), otwiera
przeglądarkę na logowanie BPP + ekran zgody (scope `read`), po czym wywołuje
narzędzia z `Bearer`. `bpp-mcp` weryfikuje token przez `GET /api/v1/whoami/` i
forwarduje token **bieżącego requestu** do `/api/v1/`. Zapis jest zablokowany
serwerowo (read-only).

**Bezpieczeństwo:** trzymaj `--host 127.0.0.1` (domyślnie). Bind na inny host
wyłącza wbudowaną ochronę DNS-rebinding SDK i eksponuje serwer poza maszynę.
Token jest forwardowany do API BPP bez wiązania `audience` (świadome odstępstwo
od MCP-MUST: `bpp-mcp` i API BPP = ta sama domena zaufania; mitygacje: scope
`read`, twardy read-only serwerowo, krótki TTL).

### Logowanie w trybie stdio (per-user, bez hostowania)

Domyślny tryb stdio może działać **z uprawnieniami zalogowanego użytkownika**
bez uruchamiania serwera HTTP. Zaloguj się **raz**:

```bash
BPP_BASE_URL=https://bpp.twoja-uczelnia.pl \
  uvx --from git+https://github.com/iplweb/bpp-mcp bpp-mcp login
```

Otworzy się przeglądarka na logowanie BPP (hasło/LDAP/Microsoft/ORCID/Keycloak)
i ekran zgody (scope `read`). Po zalogowaniu token trafia do lokalnego pliku
`~/.config/bpp-mcp/<instancja>/tokens.json` (uprawnienia `0600`), a `bpp-mcp`
uruchamiany przez Claude forwarduje go do `/api/v1/` — bez dodatkowych kroków.

**Praca zdalna / host bez GUI.** Adres autoryzacji jest zawsze wypisywany też
tekstem, więc można go otworzyć w przeglądarce na innej maszynie. Callback na
`127.0.0.1` wtedy nie wróci (przeglądarka jest gdzie indziej) — po zalogowaniu
skopiuj z paska adresu cały adres przekierowania (zaczyna się od
`http://127.0.0.1:`) albo sam parametr `code` i wklej w terminalu, gdzie czeka
`bpp-mcp login`. Obie drogi — loopback i wklejka — działają równolegle; liczy
się ta, która dojdzie pierwsza.

Co odblokowuje:

- **bogatsze wyniki** istniejących narzędzi (rekordy widoczne dla Twojego konta),
- narzędzia **`zapytanie_rekord` / `zapytanie_autor` / `zapytanie_autorzy`**
  (wykonywanie DjangoQL) — wymagają zalogowania i uprawnień redaktora.

Wylogowanie (usuwa token tej instancji):

```bash
BPP_BASE_URL=https://bpp.twoja-uczelnia.pl \
  uvx --from git+https://github.com/iplweb/bpp-mcp bpp-mcp logout
```

**Gdy instancja nie wystawia `/.well-known/`.** Logowanie zaczyna się od
odczytu metadanych serwera autoryzacji (RFC 8414) spod
`/.well-known/oauth-authorization-server`. Część wdrożeń blokuje na brzegu cały
`/.well-known/` (typowo regułą nginksa na pliki ukryte, `location ~ /\.`) i
oddaje `403`, mimo że serwer autoryzacji działa. `bpp-mcp` cofa się wtedy na
konwencjonalne ścieżki django-oauth-toolkit (`/o/authorize/`, `/o/token/`,
`/o/register/`) na tym samym hoście i loguje normalnie. Prawidłowo wystawione
metadane zawsze mają pierwszeństwo. Właściwą naprawą po stronie serwera jest
`location ^~ /.well-known/` przed regułą na pliki ukryte — bez tego natywny
przycisk „authorize" w trybie HTTP nadal nie zadziała (tam discovery robi sam
klient Claude, nie `bpp-mcp`).

Token jest krótkotrwały (access ~30 min) i odświeżany po cichu (refresh ~7 dni,
rotujący). Zmiana hasła lub dezaktywacja konta w BPP unieważnia go — wtedy
`bpp-mcp` wraca do trybu anonimowego, a narzędzia `zapytanie_*` poproszą o
ponowne `bpp-mcp login`. Host bierze z `BPP_BASE_URL` (wymagany).

**Różnica względem trybu HTTP:** natywny przycisk „authorize" w Claude (jak przy
GitHub) należy do trybu HTTP (sekcja wyżej) — wymaga działającego serwera pod
URL-em. Tryb stdio nie pokazuje tego przycisku; logowanie przeprowadza komenda
`bpp-mcp login`. Oba forwardują token do tego samego API i wykluczają zapis
(read-only serwerowo).

## Podłączenie do Claude Desktop

Dodaj wpis w pliku konfiguracyjnym Claude Desktop
(`claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "bpp": {
      "command": "uvx",
      "args": ["--from", "git+https://github.com/iplweb/bpp-mcp", "bpp-mcp"],
      "env": {
        "BPP_BASE_URL": "https://bpp.twoja-uczelnia.pl"
      }
    }
  }
}
```

## Podłączenie do Claude Code

```bash
claude mcp add bpp \
  --env BPP_BASE_URL=https://bpp.twoja-uczelnia.pl \
  -- uvx --from git+https://github.com/iplweb/bpp-mcp bpp-mcp
```

## Narzędzia

| Narzędzie | Rola |
|---|---|
| `szukaj_publikacji(q, rok_od?, rok_do?, limit=25)` | rankowane wyszukiwanie pełnotekstowe publikacji |
| `szukaj_autora(nazwisko)` | znajdź autorów po (bieżącym) nazwisku |
| `publikacje_autora(id_lub_slug, rok_od?, rok_do?, limit=25)` | publikacje autora (ID lub slug) |
| `publikacje_jednostki(id_lub_slug, rok_od?, rok_do?, limit=25)` | publikacje jednostki i pod-jednostek |
| `pobierz_rekord(typ, id, pelne_dane_autorow=False)` | detal rekordu z rozwiniętymi relacjami |
| `lista_publikacji(typ, rok_od?, rok_do?, charakter_formalny?, zmienione_po?, limit=25, offset=0)` | harvest/przyrost listy publikacji |
| `slownik(rodzaj)` | mały słownik referencyjny (tłumaczenie ID↔nazwa) |
| `zapytanie_rekord(q, limit=25, offset=0)` | **wykonaj** DjangoQL po publikacjach (`bpp.Rekord`) — autoryzowane |
| `zapytanie_autor(q, limit=25, offset=0)` | **wykonaj** DjangoQL po autorach (`bpp.Autor`) — autoryzowane |
| `zapytanie_autorzy(q, limit=25, offset=0)` | **wykonaj** DjangoQL po wpisach autorstwa (`bpp.Autorzy`) — autoryzowane |
| `djangoql_schema(model="rekord")` | schemat DjangoQL-dla-LLM korzenia `rekord`/`autor`/`autorzy` (do budowy zapytań) |

**Zapytania DjangoQL (`zapytanie_*`) są AUTORYZOWANE** — endpointy
`/api/v1/zapytanie/{rekord,autor,autorzy}/` wymagają `Bearer` (tryb OAuth/HTTP,
patrz wyżej) albo sesji, oraz uprawnień redaktora (superuser lub staff w grupie
„wprowadzanie danych"). Bez tego zwracają czytelny błąd: 401 (token), 403 (brak
uprawnień), 400 (zła składnia/pole, z pozycją do korekty; pola PII jak
`autor.email` są zablokowane), 503 (timeout — zawęź). Buduj zapytanie z
`djangoql_schema("rekord")`; w trybie stdio bez tokenu dostaniesz 401/403.

Dodatkowo serwer wystawia **prompt** MCP (nie narzędzie wykonujące):

| Prompt | Rola |
|---|---|
| `zloz_zapytanie_djangoql(opis)` | złóż zapytanie DjangoQL (z opisu po polsku) — wykonasz je `zapytanie_rekord` |

`typ` w `pobierz_rekord` / `lista_publikacji`: `wydawnictwo_ciagle`,
`wydawnictwo_zwarte`, `patent`, `praca_doktorska`, `praca_habilitacyjna`.

`rodzaj` w `slownik`: `charakter_formalny`, `typ_kbn`, `jezyk`,
`dyscyplina_naukowa`, `rodzaj_zrodla`, `poziom_wydawcy`, `funkcja_autora`,
`tytul`, `czas_udostepnienia_openaccess`. Dane wolumenowe
(konferencja/wydawca/nagroda) są odrzucane — to nie słowniki.

### Uwagi

- **`szukaj_publikacji` i `szukaj_autora` wymagają instancji BPP z Fazą 0**
  (rozszerzenie API o wyszukiwanie). Na starszej instancji `szukaj_publikacji`
  zwróci czytelny błąd (404 → komunikat o wymaganej wersji).
- **`zapytanie_rekord/autor/autorzy` wymagają nowszej instancji BPP** (z
  endpointami `/api/v1/zapytanie/*`) **oraz uwierzytelnienia** (Bearer/sesja +
  uprawnienia redaktora) — patrz tabela wyżej. Pozostałe narzędzia
  (`publikacje_*`, `pobierz_rekord`, `lista_publikacji`, `slownik`) są anonimowe
  i działają na każdej wersji API.
- **`szukaj_autora` — wykrywanie możliwości:** django-filter po cichu ignoruje
  nieznane parametry. Na starej instancji filtr `nazwisko` zostanie
  zignorowany i endpoint zwróci *wszystkich* autorów bez błędu. Narzędzie
  ustawia wtedy flagę `mozliwe_ze_niefiltrowane` (gdy trafień jest podejrzanie
  dużo). Filtr obejmuje wyłącznie bieżące `nazwisko` (nie `poprzednie_nazwiska`).
- **`publikacje_autora` / `publikacje_jednostki`** mają twardy sufit 100
  pozycji (endpoint `recent_*`). Przy dobiciu do limitu zwracana jest flaga
  `obcieto: true` — pełny harvest per autor rób przez `lista_publikacji`
  z chunkowaniem po latach. Endpoint `recent_*` NIE zwraca łącznej liczby
  prac encji (jego `count` to tylko liczba pozycji po obcięciu), dlatego
  narzędzie eksponuje wyłącznie `zwrocono` (liczba zwróconych) + `obcieto`,
  bez mylącego `count`.
- **`szukaj_publikacji` / `szukaj_autora` / `lista_publikacji`** zwracają
  `laczna_liczba` (serwerowy `count` — realna liczba trafień), `zwrocono`
  (ile faktycznie przyszło) oraz flagę `niepelne`. `niepelne: true` oznacza,
  że auto-follow paginacji przerwał bezpiecznik (sufit liczby stron / zapętlony
  `next`) zanim objął wszystko — wynik może być niekompletny.

## DjangoQL — schemat do budowy zapytań (`djangoql_schema`)

`djangoql_schema(model)` zwraca zbundlowany, bezpieczny schemat jednego z trzech
korzeni — `rekord` (`bpp.Rekord`), `autor` (`bpp.Autor`), `autorzy`
(`bpp.Autorzy`) — po jednym na endpoint `/api/v1/zapytanie/*`
dla języka [DjangoQL](https://github.com/ivelum/djangoql): reguły gramatyki
(operatory per typ, negacja, trawersowanie relacji, sufiksy `__year` / `__count`
itd.), pola z typami oraz sekcję `dictionaries` z dozwolonymi WARTOŚCIAMI
wyłącznie bezpiecznych słowników zamkniętych (charaktery, dyscypliny, języki,
licencje OA…). W schemacie NIE ma żadnych danych osób ani instytucji.

Dzięki temu LLM może zbudować PRECYZYJNE zapytanie, np.:

```text
rok >= 2020 and jezyk.nazwa = "angielski" and impact_factor > 0
```

- **Konstrukcja tu, wykonanie osobno.** To narzędzie tylko *buduje* zapytania.
  Wykonasz je narzędziami `zapytanie_rekord` / `zapytanie_autor` /
  `zapytanie_autorzy` (patrz tabela narzędzi) — wymagają zalogowania
  (Bearer/sesja + uprawnienia redaktora); anonimowo zwracają 401/403.
- **Wersjonowanie.** Pierwsza linia schematu to `# BPP <wersja>` (np.
  `# BPP 202607.1397`). Plik jest generowany per wersja BPP i powinien pasować
  do odpytywanej instancji. Źródło: repo
  [iplweb/bpp-schema-for-llm](https://github.com/iplweb/bpp-schema-for-llm)
  (schemat przeskanowany — bez danych osobowych). Plik jest zbundlowany jako
  zasób pakietu (`bpp_mcp/data/`) i wczytywany przez `importlib.resources`.

### Prompt `zloz_zapytanie_djangoql(opis)` — złóż zapytanie do wklejenia

Serwer wystawia prompt MCP `zloz_zapytanie_djangoql(opis)`. To **nie** jest
narzędzie wykonujące — prompt zwraca instrukcję dla klienta LLM, jak z opisu po
polsku ułożyć jedno poprawne zapytanie DjangoQL. Instrukcja każe najpierw
wywołać `djangoql_schema("rekord")` (jedyne źródło pól, typów, relacji i wartości
`dictionaries`), podaje zwięzłe reguły (operator wg typu, trawersacja relacji
kropką, wartości słownikowe dosłownie, negacja tylko `!=`/`!~`/`not in`,
łączenie `and`/`or` + nawiasy), a na końcu każe zwrócić gotowe zapytanie w bloku
kodu. **Wykonasz** je narzędziem `zapytanie_rekord` (po zalogowaniu) albo wklejasz
w edytor „zapytanie" BPP — prompt, tak jak `djangoql_schema`, tylko *konstruuje*,
nie *wykonuje*.

## Rozwój

```bash
uv sync --extra dev
uv run ruff format .
uv run ruff check .
uv run pytest -q
```

Testy są w pełni offline (mock httpx przez [respx](https://lundberg.github.io/respx/));
domyślne CI nie wykonuje żadnych żywych wywołań.

## Licencja

MIT — IPLWeb / Michał Pasternak. Patrz [LICENSE](LICENSE).
