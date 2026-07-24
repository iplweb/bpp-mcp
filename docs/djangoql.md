# DjangoQL — schemat do budowy zapytań

`djangoql_schema(model)` zwraca zbundlowany, bezpieczny schemat jednego z trzech
korzeni — `rekord` (`bpp.Rekord`), `autor` (`bpp.Autor`), `autorzy`
(`bpp.Autorzy`) — po jednym na endpoint `/api/v1/zapytanie/*` dla języka
[DjangoQL](https://github.com/ivelum/djangoql): reguły gramatyki (operatory per
typ, negacja, trawersowanie relacji, sufiksy `__year` / `__count` itd.), pola z
typami oraz sekcję `dictionaries` z dozwolonymi WARTOŚCIAMI wyłącznie bezpiecznych
słowników zamkniętych (charaktery, dyscypliny, języki, licencje OA…). W schemacie
NIE ma żadnych danych osób ani instytucji.

Dzięki temu LLM może zbudować PRECYZYJNE zapytanie, np.:

```text
rok >= 2020 and jezyk.nazwa = "angielski" and impact_factor > 0
```

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
`dictionaries`), podaje zwięzłe reguły (operator wg typu, trawersacja relacji
kropką, wartości słownikowe dosłownie, negacja tylko `!=`/`!~`/`not in`, łączenie
`and`/`or` + nawiasy), a na końcu każe zwrócić gotowe zapytanie w bloku kodu.
**Wykonasz** je narzędziem `zapytanie_rekord` (po zalogowaniu) albo wklejasz w
edytor „zapytanie" BPP — prompt, tak jak `djangoql_schema`, tylko *konstruuje*,
nie *wykonuje*.
