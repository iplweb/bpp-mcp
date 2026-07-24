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
