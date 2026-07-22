# Porcjowanie schematu DjangoQL w `djangoql_schema`

Data: 2026-07-22
Repo: `bpp-mcp`
Status: zaakceptowany design, do implementacji

## Problem

`djangoql_schema(model)` zwraca cały zbundlowany snapshot schematu w jednym
wyniku narzędzia MCP. Dla korzenia `rekord` to 74 437 znaków tekstu, po
opakowaniu w JSON — 77 001 znaków. Klient (Claude Code) ma sufit na wielkość
pojedynczego wyniku narzędzia MCP (domyślnie 25 000 tokenów, zmienna
`MAX_MCP_OUTPUT_TOKENS`). Wynik go przekracza, więc klient zapisuje go do pliku
tymczasowego zamiast oddać modelowi — narzędzie przestaje działać w swoim
podstawowym zastosowaniu.

Nie jest to awaria serwera BPP ani błąd generatora schematu. To skutek tego, że
narzędzie oddaje cały zasób naraz, podczas gdy pozostałe narzędzia `bpp-mcp`
porcjują wyniki (`limit` / `offset`).

### Rozkład ładunku (korzeń `rekord`)

| fragment | rozmiar | udział |
|---|---|---|
| preambuła (reguły języka DjangoQL, `start model:`) | 1,6 kB | 2% |
| sekcja modelu-korzenia `bpp.rekord` | 3,9 kB | 5% |
| sekcja `dictionaries` (dozwolone wartości słowników) | 13,2 kB | 18% |
| pozostałe 62 sekcje modeli relacyjnych | 55,5 kB | 75% |

Trzy czwarte ładunku to opisy modeli osiągalnych przez relacje
(`pbn_api.scientist`, `bpp.patent_autor`, `bpp.cache_punktacja_autora` …), po
które konkretne zapytanie sięga sporadycznie.

## Decyzje

### Zmiana idzie wyłącznie do `bpp-mcp`

Snapshot istnieje w trzech identycznych kopiach: w głównym BPP
(`src/bpp/data/*.compact.txt`, generowany komendą
`opisz_schemat_djangoql_dla_llm`), w `bpp-mcp` (`src/bpp_mcp/data/`) oraz w
`bpp-skills` (`bpp-api/references/*-djangoql-schema.txt`).

Limit dotyczy wyłącznie ścieżki MCP. Skill czyta ten sam plik narzędziem `Read`
z `offset`/`limit`, więc porcjuje z natury. Główne BPP nie serwuje tego pliku w
runtime — poza generatorem i testami nie ma w `src/` konsumentów. Format
`compact` ma już jednoznaczne granice sekcji, więc krojenie da się zrobić
parsowaniem po stronie `bpp-mcp`, bez zmiany generatora, bez bumpa wersji BPP i
bez regeneracji trzech kopii.

Kosztem jest sprzężenie `bpp-mcp` z formatem tekstowym generatora. Kryjemy je
testem kontraktu formatu (sekcja „Bezpiecznik formatu").

### Pełne słowniki w rdzeniu

Rdzeń zawiera całą sekcję `dictionaries` (13,2 kB), bez obcinania — mimo że
sam `bpp.jezyk` to 6,8 kB (480 nazw języków ISO, 52% bloku słowników).

Obcinanie odrzucone: listy wartości są alfabetyczne, więc pierwsze N wartości
`bpp.jezyk` to „abchaski, Achinese, Acoli…", podczas gdy realnie używane
„polski" i „angielski" wypadłyby poza próg. Model dostałby prefiks wyglądający
na kompletny zbiór zamknięty — gorzej niż brak danych. Pełne słowniki
eliminują też całą klasę halucynacji wartości i nie wymagają żadnej logiki
progów.

### Rdzeń bez wyjątków dla `bpp.autorzy`

Rdzeń to zawsze: preambuła + sekcja modelu-korzenia + `dictionaries`. Bez
specjalnego traktowania `bpp.autorzy`, mimo że trawersacja
`autorzy.autor.nazwisko` jest najczęstsza. Nazwa sekcji i tak jest widoczna w
bloku `bpp.rekord` jako `autorzy -> bpp.autorzy?`, a docstring narzędzia
instruuje model, żeby dobrał sekcje dla relacji, których będzie używać. Reguła
bez wyjątków jest łatwiejsza do wytłumaczenia modelowi i do przetestowania.

### Brak furtki „zwróć wszystko"

Nie dodajemy parametru zwracającego cały plik. To dokładnie ta ścieżka, która
wysadza limit. Kto potrzebuje całości, ma plik na dysku w pakiecie.

## Rozmiary po zmianie

Zweryfikowane parsowaniem wszystkich trzech zbundlowanych plików (każdy ma
63 sekcje modeli):

| korzeń | rdzeń | udział pliku |
|---|---|---|
| `rekord` | 18 126 B (~5,5k tok) | 25% |
| `autor` | 16 943 B (~5,2k tok) | 23% |
| `autorzy` | 14 874 B (~4,5k tok) | 20% |

Pojedyncza dobrana sekcja modelu: 0,3–8,4 kB (mediana ~0,9 kB).

## Architektura

### Nowy moduł `src/bpp_mcp/schemat.py`

Czysty parser tekstu: bez I/O, bez sieci, bez zależności od `tools.py`.
Testowalny na sztucznym tekście, bez dotykania zasobów pakietu. Powód
wydzielenia: `tools.py` ma już 557 linii i miesza wywołania HTTP z logiką;
parser jest samodzielną jednostką o wąskim interfejsie.

Interfejs publiczny modułu:

```python
@dataclass(frozen=True)
class Schemat:
    preambula: str          # od początku pliku do pierwszego nagłówka sekcji
    korzen: str             # nazwa modelu-korzenia, np. "bpp.rekord"
    sekcje: dict[str, str]  # nazwa modelu -> blok tekstu, w kolejności z pliku
    slowniki: str           # blok "dictionaries (...)" do końca pliku

def podziel(tekst: str) -> Schemat
def rdzen(s: Schemat) -> str            # preambula + sekcje[korzen] + slowniki
def wytnij(s: Schemat, nazwy: Sequence[str]) -> str
```

### Reguły parsowania

Zweryfikowane na wszystkich trzech zbundlowanych plikach:

- nagłówek sekcji: linia pasująca do `^[a-z_]+\.[a-z_]+:$` w kolumnie 0
  (np. `bpp.rekord:`, `pbn_api.publication:`, `taggit.tag:`,
  `ewaluacja_common.rodzaj_autora:`); zawartość sekcji jest wcięta
- preambuła: wszystko przed pierwszym nagłówkiem sekcji; zawiera linię
  `start model: <nazwa>`, z której wyprowadzamy `korzen` (nie hardkodujemy
  mapowania `model` → nazwa sekcji)
- `dictionaries`: linia zaczynająca się od `dictionaries` w kolumnie 0; blok
  ciągnie się do końca pliku
- `sekcje` nie zawiera bloku `dictionaries` (jest osobnym polem) ani preambuły

### Zmiana w `tools.py`

`djangoql_schema` zachowuje wczytywanie pliku przez `importlib.resources`
(`_wczytaj_schemat_djangoql`) i walidację nazwy modelu, a krojenie deleguje do
`schemat.py`.

## Interfejs narzędzia

```python
async def djangoql_schema(
    model: str = "rekord",
    sekcje: list[str] | None = None,
) -> dict[str, Any]
```

Zwrot:

```python
{
    "model": "rekord",
    "schemat": "<rdzeń albo sklejone wskazane bloki>",
    "sekcje_dostepne": ["bpp.autorzy", "bpp.charakter_formalny", ...],
    "jak_zlozyc": "<wskazówka, rozszerzona o dobieranie sekcji>",
}
```

- bez `sekcje` (albo `sekcje=[]`) → `schemat` = rdzeń
- z `sekcje` → `schemat` = wskazane bloki, sklejone w kolejności z pliku
  (deterministyczna, niezależna od kolejności argumentów)
- `sekcje_dostepne` jest w zwrocie ZAWSZE (62 nazwy, ~1,2 kB) — pozwala
  poprawić literówkę w nazwie sekcji bez dodatkowej rundy wywołań
- `sekcje_dostepne` nie zawiera nazwy sekcji korzenia ani `dictionaries` — one
  są już w rdzeniu

### Rozstrzygnięcia szczegółowe

Żeby implementujący nie musiał zgadywać:

- **separator sklejania**: każdy blok jest przechowywany bez końcowych pustych
  linii; bloki skleja się `"\n\n"`, całość kończy pojedynczym `"\n"`. Rdzeń to
  `"\n\n".join([preambula, sekcja_korzenia, slowniki]) + "\n"`
- **kolejność `sekcje_dostepne`**: kolejność z pliku (nie alfabetyczna) — jest
  to kolejność pierwszego odwołania, więc modele powiązane leżą blisko siebie
- **duplikaty w `sekcje=`**: deduplikowane, wynik w kolejności z pliku
- **podanie nazwy korzenia albo `dictionaries` jako sekcji**: `BppError` z
  komunikatem, że ta sekcja jest już w rdzeniu i wystarczy wywołać narzędzie
  bez parametru `sekcje` (jawna nauka dla modelu zamiast cichego duplikatu)

### Ograniczenia narzucone przez istniejące testy

Zweryfikowane czytaniem `tests/test_djangoql_schema.py` — złamanie
któregokolwiek wywali test, który dziś przechodzi:

- **rdzeń musi zaczynać się dosłownie od preambuły** (`# BPP …`), bo
  `test_djangoql_schema_trzy_korzenie_dostepne` robi `schemat.startswith("# BPP")`.
  Informacja „to jest rdzeń, dobierz sekcje" NIE może być doklejona na początek
  tekstu schematu — idzie osobnym polem zwrotu i do docstringa
- **do `PROMPT_ZLOZ_ZAPYTANIE` nie wolno dopisać nawiasów klamrowych** — stała
  przechodzi przez `str.format(opis=…)` z jedynym placeholderem `{opis}`, więc
  każde `{` lub `}` w dopisanym tekście wysadzi wywołanie. Zapis
  `sekcje=["bpp.zrodlo"]` jest bezpieczny
- **`_JAK_ZLOZYC` musi nadal zawierać podłańcuchy** `operator`, `dictionaries`,
  `zapytanie_rekord`; **`PROMPT_ZLOZ_ZAPYTANIE`** — `djangoql_schema`,
  `operator`, `dictionaries`, `wklej`

## Obsługa błędów

Wszystkie błędy przez `BppError` (spójnie z resztą `tools.py`).

| sytuacja | zachowanie |
|---|---|
| nieznany `model` | `BppError` z listą dostępnych — bez zmian, test już istnieje |
| nieznana nazwa sekcji | `BppError` z nazwą, najbliższymi dopasowaniami (`difflib.get_close_matches`) i liczbą dostępnych sekcji |
| `sekcje=[]` | traktowane jak brak parametru → rdzeń |
| sekcja korzenia nieodnaleziona w pliku | `BppError` — patrz bezpiecznik niżej |

Kilka nieznanych nazw naraz: błąd wymienia wszystkie nieznane, nie tylko
pierwszą.

## Bezpiecznik formatu

Skoro `bpp-mcp` zależy od formatu tekstowego generatora z głównego BPP, dryf
formatu musi kończyć się głośną awarią, nie cichym zwrotem pustego schematu —
model dostawszy pusty schemat zacząłby zgadywać nazwy pól.

- **guard w kodzie**: `rdzen()` podnosi wyjątek, gdy brak sekcji korzenia albo
  gdy wynik byłby pusty
- **test kontraktu formatu**: dla każdego z trzech zbundlowanych plików —
  parsuje się na ≥50 sekcji, preambuła zawiera `start model:`, blok
  `dictionaries` istnieje i jest niepusty, sekcja korzenia istnieje i jest
  niepusta, rdzeń jest istotnie mniejszy od całego pliku (< 40%)

## Testy (TDD — testy przed implementacją)

Rozszerzenie `tests/test_djangoql_schema.py` (103 linie dziś):

Parser (na sztucznym mini-schemacie, bez zasobów pakietu):
- granice sekcji, w tym ostatnia sekcja przed `dictionaries`
- preambuła kończy się na pierwszym nagłówku
- `korzen` wyprowadzony z `start model:`
- `dictionaries` nie trafia do `sekcje`
- tekst bez `start model:` → wyjątek
- tekst bez sekcji korzenia → wyjątek

Narzędzie:
- domyślne wywołanie zwraca rdzeń zawierający preambułę, sekcję korzenia i
  `dictionaries`, a NIE zawierający sekcji spoza rdzenia
- rdzeń dla każdego z trzech korzeni jest niepusty i mniejszy niż plik
- `sekcje=["bpp.zrodlo"]` zwraca ten blok i nie zwraca rdzenia
- wiele sekcji sklejanych w kolejności z pliku, niezależnie od kolejności
  argumentów
- `sekcje=[]` równoważne brakowi parametru
- nieznana sekcja → `BppError` z sugestią
- `sekcje_dostepne` obecne w obu trybach, bez korzenia i bez `dictionaries`

Kontrakt formatu: jak w sekcji „Bezpiecznik formatu".

Zachowanie istniejących testów bez zmian tam, gdzie sprawdzają nagłówek,
wskazówkę `jak_zlozyc`, domyślny model i błąd dla nieznanego modelu.

## Do aktualizacji poza kodem

- **docstring `djangoql_schema` w `server.py`** — jedyna instrukcja, jaką widzi
  model; musi mówić wprost, że domyślnie wraca rdzeń, a sekcje dla relacji
  dobiera się parametrem `sekcje`
- **docstring w `tools.py`** — analogicznie
- **`_JAK_ZLOZYC` w `tools.py`** — dopisać zdanie o dobieraniu sekcji
- **`PROMPT_ZLOZ_ZAPYTANIE` w `server.py`** — KROK 1 mówi dziś, że wynik
  `djangoql_schema("rekord")` jest jedynym źródłem prawdy; dopisać, że dla
  relacji spoza rdzenia trzeba dobrać sekcję
- **`README.md`** — opis narzędzia (dziś w okolicy linii 259)

## Poza zakresem

- zmiany w generatorze `opisz_schemat_djangoql_dla_llm` w głównym BPP
- zmiany w `bpp-skills` (skill czyta plik `Read`-em, limitu nie ma)
- regeneracja snapshotów
- format JSON schematu
