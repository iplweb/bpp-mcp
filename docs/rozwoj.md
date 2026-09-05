# Rozwój

```bash
uv sync --extra dev
uv run ruff format .
uv run ruff check .
uv run pytest -q
```

Testy są w pełni offline (mock httpx przez
[respx](https://lundberg.github.io/respx/)); domyślne CI nie wykonuje żadnych
żywych wywołań.

## Dokumentacja

Ta dokumentacja to [MkDocs](https://www.mkdocs.org/) +
[Material](https://squidfunk.github.io/mkdocs-material/). Podgląd lokalny:

```bash
uv sync --extra docs
uv run mkdocs serve
```

Build produkcyjny (jak w CI) — `--strict` traktuje ostrzeżenia (m.in. martwe
linki) jako błędy:

```bash
uv run mkdocs build --strict
```

Po merge do `main` workflow `.github/workflows/docs.yml` publikuje stronę na
[GitHub Pages](https://iplweb.github.io/bpp-mcp/).

## Wydanie na PyPI

Publikacja idzie przez
[trusted publishing](https://docs.pypi.org/trusted-publishers/) (OIDC) — w
repozytorium nie ma i nie może być tokenu API PyPI. Wydanie wyzwala push tagu:

```bash
# 1. podbij wersję w TRZECH miejscach (niżej), zacommituj
# 2. otaguj i wypchnij
git tag vX.Y.Z
git push origin vX.Y.Z
```

Numer wersji żyje w trzech plikach i wszystkie trzy trzeba podbić razem:

| Plik | Kto to czyta |
|---|---|
| `pyproject.toml` (`project.version`) | build, PyPI — **i tylko to** porównuje z tagiem workflow wydaniowy |
| `src/bpp_mcp/__init__.py` (`__version__`) | kod w runtime |
| `manifest.json` (`version`) | bundle `.mcpb` dla Claude Desktop |

Gate w CI sprawdza wyłącznie zgodność tagu z `pyproject.toml`, więc rozjazd
dwóch pozostałych **nie przerwie wydania** — użytkownik zobaczy wtedy w
`__version__` albo w instalatorze Claude Desktop numer inny niż faktycznie
zainstalowany. Sprawdź `grep -rn '<stara-wersja>' pyproject.toml
src/bpp_mcp/__init__.py manifest.json` przed tagowaniem.

Workflow `.github/workflows/release.yml` przepuszcza pełną matrycę testów,
**sprawdza, czy tag zgadza się z `project.version`** (rozjazd = przerwane
wydanie, bo numeru raz zajętego na PyPI nie da się odzyskać), buduje sdist +
wheel, weryfikuje je `twine check --strict` i obecność zbundlowanych schematów
DjangoQL, po czym publikuje z osobnego joba w środowisku `pypi`.

## Hostowanie narzędzi w cudzym procesie

Od **0.2.0** ten pakiet da się wpiąć do aplikacji, która sama wystawia endpoint
MCP — w praktyce: do instancji BPP serwującej własne `/mcp`. Wtedy narzędzia
nie chodzą do API po sieci, tylko wołają aplikację hosta w tym samym procesie,
a użytkownik nie musi nic instalować ani znać adresu swojej uczelni.

Służą do tego cztery szwy. Wszystkie są addytywne — domyślne wartości
odtwarzają zachowanie sprzed 0.2.0.

```python
import httpx
from mcp.server.fastmcp import FastMCP
from bpp_mcp import KontekstApp, register_tools
from bpp_mcp.client import BppClient, TrybAuth

class KlientHosta(BppClient):
    def _slownik_cache(self):                            # (3)
        return cache_biezacego_zadania.get()

client = KlientHosta(
    config,
    transport=httpx.ASGITransport(app=aplikacja_hosta),  # (1)
    tryb_auth=TrybAuth.W_PROCESIE,                       # (2)
    max_retries=0,
)

mcp = FastMCP("bpp", lifespan=wlasny_lifespan, stateless_http=True)
register_tools(mcp)                                      # (4)
```

**(1) `transport=`** podstawia warstwę transportową `httpx`. Z
`httpx.ASGITransport` żądanie idzie wprost do aplikacji ASGI hosta: bez
gniazda, bez TLS-a, bez adresu, który trzeba znać. Uwaga — `ASGITransport`
**ignoruje timeouty** `httpx`, więc sufit czasu odpowiedzi musi zapewnić host.
Ponawianie też traci sens (nie ma sieci, która by zamigotała): `max_retries=0`.

**(2) `tryb_auth=TrybAuth.W_PROCESIE`** — bearer bieżącego żądania albo
anonimowo, **nigdy Basic**. Tryb `ZDALNY` (dotąd wybierany przez
`transport="http"`) przy braku bearera rzuca, co dla endpointu z dostępem
publicznym jest złe; tryb `LOKALNY` sięgnąłby po `BPP_BASIC_AUTH`, czyli po
wspólne konto omijające scope i revoke tokenu. Polityka jest od 0.2.0 rozłączna
od nazwy transportu — `config.transport` steruje już tylko treścią komunikatów.

**(3) `_slownik_cache()`** to metoda do nadpisania w podklasie. Domyślnie cache
`URL → JSON` jest jeden na instancję klienta, co jest poprawne, gdy proces
obsługuje jednego użytkownika. Klient hosta żyje w lifespan-kontekście, czyli
jest **współdzielony**, a kluczem jest sam URL — jeden słownik mieszałby wtedy
użytkowników i (w instalacji wielo-tenantowej) uczelnie. Podstaw słownik
o właściwym zasięgu, np. per-żądanie z `ContextVar`.

**(4) `register_tools(mcp)`** rejestruje komplet 11 narzędzi i 1 prompt na
instancji `FastMCP` hosta — bez kopiowania wrapperów. Kontrakt: lifespan
przekazany do `FastMCP` musi oddawać `KontekstApp` (albo obiekt o tych samych
atrybutach), bo wrappery sięgają po klienta przez
`ctx.request_context.lifespan_context`. Host wielo-użytkownikowy ustawia
`bearer_provider=None` — fallback na token z lokalnego cache ma sens wyłącznie
w stdio, inaczej token jednej osoby trafiłby do żądania innej. Zamknięcie
klienta (`await client.aclose()`) należy do lifespanu hosta.
