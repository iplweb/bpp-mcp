# Wydanie na PyPI przez Trusted Publishing

Data: 2026-07-22
Status: zaakceptowany

## Problem

`bpp-mcp` da się zainstalować wyłącznie z gita
(`uvx --from git+https://github.com/iplweb/bpp-mcp bpp-mcp`). To działa, ale:

- każdy start serwera MCP z zimnym cache uv oznacza `git clone` + budowę koła,
  czyli Claude Desktop czeka, zamiast wystartować;
- w konfiguracji Claude'a trzeba wkleić długi, łatwy do przekręcenia URL;
- nie ma pojęcia „wersja" — `git+…` zawsze bierze czubek `main`, więc dwie osoby
  mogą mieć różny kod pod tą samą konfiguracją.

Nazwa `bpp-mcp` jest na PyPI wolna (stan na 2026-07-22).

## Decyzje

| Decyzja | Wybór | Uzasadnienie |
|---|---|---|
| Wyzwalacz wydania | push tagu `v*` | tag = wydanie, atomowo, bez klikania w UI |
| Źródło wersji | ręcznie w `pyproject.toml` | zero nowych zależności; rozjazd łapie guard |
| TestPyPI | nie | jeden trusted publisher do wyklikania; jakość paczki pilnuje `twine check` |
| Pierwsze wydanie | `0.1.0` | bez sztucznego bumpa |
| Uwierzytelnienie | Trusted Publishing (OIDC) | brak długożyjącego tokenu API w sekretach repo |

## Architektura

Dwa pliki workflow, `tests.yml` staje się wywoływalny.

### `tests.yml` — dodać `workflow_call`

```yaml
on:
  push:
    branches: [main]
  pull_request:
  workflow_call:
```

Jedna linijka; workflow wydania wywołuje ten sam job zamiast duplikować matrycę
Pythona i kroki ruffa.

### `release.yml` — trzy joby, sekwencyjnie

```
tests (uses: ./.github/workflows/tests.yml)
  └── build   (guard wersji → uv build → twine check → sanity wheel → artifact)
        └── publish (environment: pypi, id-token: write → gh-action-pypi-publish)
```

**`tests`** — pełna matryca 3.10–3.13 + `ruff format --check` + `ruff check`
musi być zielona, zanim cokolwiek trafi na PyPI.

**`build`** (`permissions: contents: read`):

1. *Guard wersji.* `v0.1.0` → `0.1.0`, porównanie z `project.version` z
   `pyproject.toml` (`tomllib`, stdlib). Rozjazd = `exit 1`.
   Powód: numer wersji raz opublikowany na PyPI jest **nieodwracalny** — `yank`
   ukrywa wydanie przed resolverem, ale nie zwalnia numeru i nie pozwala wgrać
   pod nim innego pliku. Tag `v0.2.0` z paczką `0.1.0` w środku byłby błędem
   niemożliwym do naprawienia inaczej niż spaleniem kolejnego numeru.
2. `uv build` → `dist/*.whl` + `dist/*.tar.gz`.
3. `uvx twine check --strict dist/*` — README musi się renderować na PyPI
   (`--strict` traktuje ostrzeżenia renderowania jako błąd).
4. *Sanity koła.* Sprawdzenie, że w `.whl` są wszystkie trzy zasoby
   `bpp_mcp/data/*_djangoql_schema.compact.txt`. Bez nich `djangoql_schema`
   wywala się dopiero u użytkownika, w runtime — a to zasoby niebędące `*.py`,
   więc dokładnie ta klasa plików, którą packaging gubi po cichu.
5. `actions/upload-artifact` → `dist/`.

**`publish`** (`needs: build`, `environment: pypi`,
`permissions: id-token: write`):

1. `actions/download-artifact` → `dist/`.
2. `pypa/gh-action-pypi-publish`, przypięty do SHA
   (`ba38be9e461d3875417946c167d0b5f3d385a247`, v1.14.1) — spójnie z istniejącym
   przypięciem `setup-uv` w `tests.yml`.

Rozdzielenie `build`/`publish` jest celowe: `id-token: write` ma **tylko** job
publikujący, który nie uruchamia żadnego kodu z repozytorium (pobiera gotowy
artefakt i woła jedną przypiętą akcję). Gdyby build i publish były jednym
jobem, dowolny kod wykonany w buildzie — także z zależności — mógłby sięgnąć po
token OIDC.

Atestacje PEP 740 zostają domyślne (akcja generuje je sama przy
`id-token: write`).

## Kroki ręczne (poza repozytorium)

Trusted publishing wymaga, by PyPI *wiedziało*, komu ufa. Konfiguracja musi się
zgadzać co do znaku:

1. **PyPI → Your projects → Publishing → Add a pending publisher**
   - PyPI Project Name: `bpp-mcp`
   - Owner: `iplweb`
   - Repository name: `bpp-mcp`
   - Workflow name: `release.yml`
   - Environment name: `pypi`
2. **GitHub → Settings → Environments → New environment: `pypi`**
   (opcjonalnie: required reviewers — wtedy nawet push tagu nie publikuje bez
   zatwierdzenia człowieka).

*Pending publisher* to wariant dla projektu, którego jeszcze nie ma na PyPI:
pierwsze udane wydanie tworzy projekt i zamienia wpis na zwykłego trusted
publishera.

## Zmiany w README

Instalacja przechodzi na PyPI, git schodzi do roli „wersja rozwojowa":

- badge PyPI (wersja) obok badge'a testów;
- `uvx bpp-mcp` jako główna droga uruchomienia;
- `uv tool install bpp-mcp` / `pip install bpp-mcp` jako alternatywy;
- konfiguracja Claude Desktop i Claude Code na `uvx bpp-mcp` zamiast
  `uvx --from git+https://… bpp-mcp` (dotyczy też `login` / `logout`);
- instalacja z gita zostaje, opisana jako sposób na niewydany kod;
- sekcja „Wydanie" w *Rozwój*: bump wersji → tag `vX.Y.Z` → push.

## Procedura wydania

```bash
# 1. wersja w pyproject.toml → X.Y.Z, commit
# 2. tag i push
git tag vX.Y.Z
git push origin vX.Y.Z
```

Reszta dzieje się w Actions. Rozjazd tagu z `pyproject.toml` zatrzymuje
wydanie w jobie `build`, zanim cokolwiek dotknie PyPI.

## Czego świadomie NIE robimy

- **Brak automatycznego GitHub Release.** Tag wystarcza; notatki wydania to
  osobna decyzja redakcyjna, nie krok CI.
- **Brak `hatch-vcs`.** Wersja z tagu wygląda kusząco, ale buildy z brudnego
  drzewa dają numery typu `0.1.0.dev3+g1a2b3c` — więcej zamieszania niż
  pożytku przy ręcznym, rzadkim wydawaniu.
- **Brak publikacji z gałęzi innych niż tag.** Żadnych nightly na PyPI.
