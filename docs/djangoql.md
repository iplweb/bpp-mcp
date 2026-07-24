# DjangoQL — schemat do budowy zapytań

`djangoql_schema(model, sekcje=None)` zwraca **porcję** zbundlowanego,
bezpiecznego schematu jednego z trzech korzeni — `rekord` (`bpp.Rekord`), `autor`
(`bpp.Autor`), `autorzy` (`bpp.Autorzy`) — po jednym na endpoint
`/api/v1/zapytanie/*` dla języka
[DjangoQL](https://github.com/ivelum/djangoql).

## Bez parametru `sekcje` dostajesz RDZEŃ

- reguły gramatyki (operatory per typ, negacja, trawersowanie relacji, sufiksy
  `__year` / `__count` itd.),
- pola modelu-korzenia z typami i — dla relacji — polem dopasowania,
- **całą** sekcję `dictionaries` z dozwolonymi WARTOŚCIAMI wyłącznie bezpiecznych
  słowników zamkniętych (charaktery, dyscypliny, języki, licencje OA…), bez
  obcinania.

W schemacie NIE ma żadnych danych osób ani instytucji.

Dzięki temu LLM może zbudować PRECYZYJNE zapytanie, np.:

```text
rok >= 2020 and jezyk.nazwa = "angielski" and impact_factor > 0
```

## Sekcje modeli relacyjnych — na żądanie

Pól `bpp.zrodlo`, `bpp.jednostka`, `pbn_api.publication` itd. w rdzeniu nie ma —
nazwy tych sekcji widać w blokach relacji modelu-korzenia (zapis
`zrodlo -> bpp.zrodlo`) oraz w polu zwrotu `sekcje_dostepne` (obecnym zawsze, w
obu trybach, bez korzenia i bez `dictionaries`). Wywołanie:

```text
djangoql_schema("rekord", sekcje=["bpp.zrodlo", "bpp.jednostka"])
```

zwraca **wyłącznie** wskazane bloki (bez preambuły i bez słowników), sklejone w
kolejności z pliku — kolejność argumentów nie ma znaczenia, duplikaty są
pomijane. Nieznana nazwa kończy się błędem z podpowiedziami (`difflib`), a podanie
korzenia albo `dictionaries` — informacją, że są już w rdzeniu.

**Typowy przepływ:** jedno wywołanie po rdzeń i (opcjonalnie) jedno po komplet
potrzebnych sekcji.

!!! note "Dlaczego porcjowanie"
    Cały snapshot korzenia `rekord` to ~74 kB tekstu i przebijał sufit wielkości
    pojedynczego wyniku narzędzia MCP (domyślnie 25 000 tokenów, zmienna
    `MAX_MCP_OUTPUT_TOKENS`) — klient odkładał wynik do pliku tymczasowego zamiast
    oddać go modelowi. Rdzeń to 20–25% snapshotu (`rekord` ~18 kB, `autor` ~17 kB,
    `autorzy` ~15 kB), a pojedyncza dobrana sekcja 0,3–8,4 kB. Nie ma parametru
    „zwróć wszystko" — kto potrzebuje całości, ma plik na dysku w pakiecie
    (`bpp_mcp/data/`).

## Uwagi

- **Konstrukcja tu, wykonanie osobno.** To narzędzie tylko *buduje* zapytania.
  Wykonasz je narzędziami `zapytanie_rekord` / `zapytanie_autor` /
  `zapytanie_autorzy` (patrz [Narzędzia](narzedzia.md)) — wymagają zalogowania
  (Bearer/sesja + uprawnienia redaktora; patrz
  [Uwierzytelnianie](uwierzytelnianie.md)); anonimowo zwracają 401/403.
- **Wersjonowanie.** Pierwsza linia schematu to `# BPP <wersja>` (np.
  `# BPP 202607.1397`). Plik jest generowany per wersja BPP i powinien pasować do
  odpytywanej instancji. Źródło: repo
  [iplweb/bpp-schema-for-llm](https://github.com/iplweb/bpp-schema-for-llm)
  (schemat przeskanowany — bez danych osobowych). Plik jest zbundlowany jako zasób
  pakietu (`bpp_mcp/data/`) i wczytywany przez `importlib.resources`.

## Prompt `zloz_zapytanie_djangoql(opis)`

Serwer wystawia prompt MCP `zloz_zapytanie_djangoql(opis)`. To **nie** jest
narzędzie wykonujące — prompt zwraca instrukcję dla klienta LLM, jak z opisu po
polsku ułożyć jedno poprawne zapytanie DjangoQL. Instrukcja każe najpierw wywołać
`djangoql_schema("rekord")` (jedyne źródło pól, typów, relacji i wartości
`dictionaries`) i — dla relacji spoza rdzenia — dobrać sekcje parametrem `sekcje`,
podaje zwięzłe reguły (operator wg typu, trawersacja relacji kropką, wartości
słownikowe dosłownie, negacja tylko `!=`/`!~`/`not in`, łączenie `and`/`or` +
nawiasy), a na końcu każe zwrócić gotowe zapytanie w bloku kodu. **Wykonasz** je
narzędziem `zapytanie_rekord` (po zalogowaniu) albo wklejasz w edytor „zapytanie"
BPP — prompt, tak jak `djangoql_schema`, tylko *konstruuje*, nie *wykonuje*.
