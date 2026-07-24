# Narzędzia

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

!!! warning "Zapytania DjangoQL (`zapytanie_*`) są AUTORYZOWANE"
    Endpointy `/api/v1/zapytanie/{rekord,autor,autorzy}/` wymagają `Bearer` (tryb
    OAuth/HTTP lub logowanie stdio — patrz [Uwierzytelnianie](uwierzytelnianie.md))
    albo sesji, oraz uprawnień redaktora (superuser lub staff w grupie
    „wprowadzanie danych"). Bez tego zwracają czytelny błąd: 401 (token), 403
    (brak uprawnień), 400 (zła składnia/pole, z pozycją do korekty; pola PII jak
    `autor.email` są zablokowane), 503 (timeout — zawęź). Buduj zapytanie z
    `djangoql_schema("rekord")` (patrz [DjangoQL](djangoql.md)); w trybie stdio
    bez tokenu dostaniesz 401/403.

Dodatkowo serwer wystawia **prompt** MCP (nie narzędzie wykonujące):

| Prompt | Rola |
|---|---|
| `zloz_zapytanie_djangoql(opis)` | złóż zapytanie DjangoQL (z opisu po polsku) — wykonasz je `zapytanie_rekord` |

## Wartości parametrów

`typ` w `pobierz_rekord` / `lista_publikacji`: `wydawnictwo_ciagle`,
`wydawnictwo_zwarte`, `patent`, `praca_doktorska`, `praca_habilitacyjna`.

`rodzaj` w `slownik`: `charakter_formalny`, `typ_kbn`, `jezyk`,
`dyscyplina_naukowa`, `rodzaj_zrodla`, `poziom_wydawcy`, `funkcja_autora`,
`tytul`, `czas_udostepnienia_openaccess`. Dane wolumenowe
(konferencja/wydawca/nagroda) są odrzucane — to nie słowniki.

## Uwagi

- **`szukaj_publikacji` i `szukaj_autora` wymagają instancji BPP z Fazą 0**
  (rozszerzenie API o wyszukiwanie). Na starszej instancji `szukaj_publikacji`
  zwróci czytelny błąd (404 → komunikat o wymaganej wersji).
- **`zapytanie_rekord/autor/autorzy` wymagają nowszej instancji BPP** (z
  endpointami `/api/v1/zapytanie/*`) **oraz uwierzytelnienia** (Bearer/sesja +
  uprawnienia redaktora) — patrz sekcja wyżej. Pozostałe narzędzia
  (`publikacje_*`, `pobierz_rekord`, `lista_publikacji`, `slownik`) są anonimowe
  i działają na każdej wersji API.
- **`szukaj_autora` — wykrywanie możliwości:** django-filter po cichu ignoruje
  nieznane parametry. Na starej instancji filtr `nazwisko` zostanie zignorowany i
  endpoint zwróci *wszystkich* autorów bez błędu. Narzędzie ustawia wtedy flagę
  `mozliwe_ze_niefiltrowane` (gdy trafień jest podejrzanie dużo). Filtr obejmuje
  wyłącznie bieżące `nazwisko` (nie `poprzednie_nazwiska`).
- **`publikacje_autora` / `publikacje_jednostki`** mają twardy sufit 100 pozycji
  (endpoint `recent_*`). Przy dobiciu do limitu zwracana jest flaga
  `obcieto: true` — pełny harvest per autor rób przez `lista_publikacji` z
  chunkowaniem po latach. Endpoint `recent_*` NIE zwraca łącznej liczby prac
  encji (jego `count` to tylko liczba pozycji po obcięciu), dlatego narzędzie
  eksponuje wyłącznie `zwrocono` (liczba zwróconych) + `obcieto`, bez mylącego
  `count`.
- **`szukaj_publikacji` / `szukaj_autora` / `lista_publikacji`** zwracają
  `laczna_liczba` (serwerowy `count` — realna liczba trafień), `zwrocono` (ile
  faktycznie przyszło) oraz flagę `niepelne`. `niepelne: true` oznacza, że
  auto-follow paginacji przerwał bezpiecznik (sufit liczby stron / zapętlony
  `next`) zanim objął wszystko — wynik może być niekompletny.
