# bpp-mcp

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
| `BPP_BASE_URL` | `https://bpp.umlub.pl` | bazowy URL instancji BPP |
| `BPP_BASIC_AUTH` | *(brak)* | opcjonalny `user:pass` (tylko raporty slotów) |

## Instalacja i uruchomienie

Najprościej, bezpośrednio z gita przez [uv](https://docs.astral.sh/uv/):

```bash
uvx --from git+https://github.com/iplweb/bpp-mcp bpp-mcp
```

Albo instalacja pip z gita:

```bash
pip install "git+https://github.com/iplweb/bpp-mcp"
bpp-mcp
```

Serwer komunikuje się po stdio (standard MCP) — normalnie uruchamia go klient
MCP, nie użytkownik ręcznie.

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
        "BPP_BASE_URL": "https://bpp.umlub.pl"
      }
    }
  }
}
```

## Podłączenie do Claude Code

```bash
claude mcp add bpp \
  --env BPP_BASE_URL=https://bpp.umlub.pl \
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
| `djangoql_schema(model="rekord")` | schemat DjangoQL-dla-LLM modelu Rekord (do budowy zapytań) |

`typ` w `pobierz_rekord` / `lista_publikacji`: `wydawnictwo_ciagle`,
`wydawnictwo_zwarte`, `patent`, `praca_doktorska`, `praca_habilitacyjna`.

`rodzaj` w `slownik`: `charakter_formalny`, `typ_kbn`, `jezyk`,
`dyscyplina_naukowa`, `rodzaj_zrodla`, `poziom_wydawcy`, `funkcja_autora`,
`tytul`, `czas_udostepnienia_openaccess`. Dane wolumenowe
(konferencja/wydawca/nagroda) są odrzucane — to nie słowniki.

### Uwagi

- **`szukaj_publikacji` i `szukaj_autora` wymagają instancji BPP z Fazą 0**
  (rozszerzenie API o wyszukiwanie). Na starszej instancji `szukaj_publikacji`
  zwróci czytelny błąd (404 → komunikat o wymaganej wersji). Pozostałe pięć
  narzędzi działa na każdej wersji API.
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

`djangoql_schema()` zwraca zbundlowany, bezpieczny schemat modelu `bpp.Rekord`
dla języka [DjangoQL](https://github.com/ivelum/djangoql): reguły gramatyki
(operatory per typ, negacja, trawersowanie relacji, sufiksy `__year` / `__count`
itd.), pola z typami oraz sekcję `dictionaries` z dozwolonymi WARTOŚCIAMI
wyłącznie bezpiecznych słowników zamkniętych (charaktery, dyscypliny, języki,
licencje OA…). W schemacie NIE ma żadnych danych osób ani instytucji.

Dzięki temu LLM może zbudować PRECYZYJNE zapytanie, np.:

```text
rok >= 2020 and jezyk.nazwa = "angielski" and impact_factor > 0
```

- **Konstrukcja tak — wykonanie NIE.** To narzędzie tylko *buduje* zapytania.
  Samo *wykonanie* wyszukiwania DjangoQL (funkcja „zapytanie" w BPP) jest dziś
  dostępne WYŁĄCZNIE dla użytkownika **zalogowanego** i nie istnieje w publicznym,
  anonimowym API — dlatego serwer nie ma narzędzia je uruchamiającego. Gdy
  anon-API zyska taką możliwość, dołożymy osobne `zapytanie(query)` (miejsce
  oznaczone `TODO` w `server.py`).
- **Wersjonowanie.** Pierwsza linia schematu to `# BPP <wersja>` (np.
  `# BPP 202607.1397`). Plik jest generowany per wersja BPP i powinien pasować
  do odpytywanej instancji. Źródło: repo
  [iplweb/bpp-schema-for-llm](https://github.com/iplweb/bpp-schema-for-llm)
  (schemat przeskanowany — bez danych osobowych). Plik jest zbundlowany jako
  zasób pakietu (`bpp_mcp/data/`) i wczytywany przez `importlib.resources`.

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
