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
# 1. podbij `version` w pyproject.toml, zacommituj
# 2. otaguj i wypchnij
git tag vX.Y.Z
git push origin vX.Y.Z
```

Workflow `.github/workflows/release.yml` przepuszcza pełną matrycę testów,
**sprawdza, czy tag zgadza się z `project.version`** (rozjazd = przerwane
wydanie, bo numeru raz zajętego na PyPI nie da się odzyskać), buduje sdist +
wheel, weryfikuje je `twine check --strict` i obecność zbundlowanych schematów
DjangoQL, po czym publikuje z osobnego joba w środowisku `pypi`.
