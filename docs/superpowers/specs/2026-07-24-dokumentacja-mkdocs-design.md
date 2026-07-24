# Spec: Dokumentacja `bpp-mcp` (MkDocs Material + GitHub Pages)

**Data:** 2026-07-24
**Autor:** brainstorming z użytkownikiem (Michał Pasternak)
**Status:** zatwierdzony do implementacji

## 1. Cel

README `bpp-mcp` (260 linii) łączy zbyt wiele: rationale, konfigurację ENV,
instalację, tryby OAuth/stdio-login, per-klient, tabelę narzędzi, DjangoQL i
notatki deweloperskie. Chcemy:

1. Wydzielić pełną dokumentację do katalogu `docs/` jako statyczną stronę
   **MkDocs + Material**, hostowaną na **GitHub Pages** i przebudowywaną w CI.
2. Skrócić README do **landingu** (~60–70 linii): czym to jest, dlaczego MCP,
   quick-start, link do pełnej dokumentacji, licencja.
3. Dodać **osobne strony „jak podłączyć bpp-mcp"** dla kluczowych klientów MCP,
   z zweryfikowanymi (2026-07-24) instrukcjami i linkami do oficjalnych docs.

## 2. Decyzje (zatwierdzone przez użytkownika)

| Decyzja | Wybór |
|---|---|
| Generator | **MkDocs + Material** |
| Zakres klientów | **Rekomendowany zestaw** (10 stron + zbiorcze `inne.md`) |
| Zakres README | **Landing** — reszta treści → `docs/` |
| Język strony | **polski** (jak README) |
| Hosting | **GitHub Pages** przez GitHub Actions (Pages już włączone przez usera ✅) |
| Accuracy | Każda strona klienta **linkuje do oficjalnej dokumentacji**; config w treści, docs = źródło prawdy |

## 3. Struktura `docs/`

```
docs/
  index.md               # co to jest + „Dlaczego MCP" (z README)
  instalacja.md          # OGÓLNA: wymagania (Python 3.10+, uv), uvx, pip, weryfikacja
  konfiguracja.md        # zmienne ENV (tabela), wielo-instancyjność
  uwierzytelnianie.md    # 3 tryby: stdio-anon / stdio-login (per-user) / HTTP-OAuth + bezpieczeństwo
  klienci/
    index.md             # przegląd: stdio vs HTTP, tabela „który klient jak", jak wybrać
    claude-desktop.md
    claude-code.md
    chatgpt.md           # tylko HTTP (remote) — wymaga bpp-mcp --http pod publicznym URL
    opencode.md
    deepseek.md          # brak własnej apki → przez klienta (Cherry Studio) + klucz API DeepSeek
    cursor.md
    vscode-copilot.md
    windsurf.md
    lm-studio.md
    zed.md
    inne.md              # Cline, Continue.dev, Goose, Cherry Studio, 5ire, JetBrains AI/Junie, Warp
  narzedzia.md           # tabela narzędzi + „Uwagi" (z README)
  djangoql.md            # schemat djangoql_schema + prompt zloz_zapytanie_djangoql (z README)
  rozwoj.md              # dev: uv sync --extra dev, ruff, pytest (z README)
  _snippets/             # wspólne bloki (DRY)
    uvx-cmd.md           # komenda uvx --from git+... bpp-mcp
    env-block.md         # objaśnienie BPP_BASE_URL
    stdio-vs-http.md     # admonition: kiedy stdio, kiedy --http
    path-caveat.md       # uvx musi być na PATH (GUI apps) — inaczej pełna ścieżka
```

**DRY:** powtarzalne bloki (komenda uvx, objaśnienie env, ostrzeżenie o PATH,
stdio-vs-HTTP) trzymamy w `docs/_snippets/` i wciągamy przez
`pymdownx.snippets` — nie kopiujemy ich do 10 stron.

## 4. `mkdocs.yml`

- `theme: material`, `language: pl`, paleta light/dark z przełącznikiem
  (`palette` z `scheme: default` / `slate`, toggle).
- `features`: `navigation.sections`, `navigation.top`, `navigation.footer`,
  `content.code.copy`, `search.highlight`, `search.suggest`.
- `markdown_extensions`: `admonition`, `pymdownx.details`,
  `pymdownx.superfences`, `pymdownx.highlight`, `pymdownx.inlinehilite`,
  `pymdownx.snippets` (z `base_path: [docs/_snippets]`),
  `pymdownx.tabbed` (`alternate_style: true` — zakładki OS / lokalizacje configu),
  `tables`, `attr_list`, `toc` (`permalink: true`).
- `repo_url: https://github.com/iplweb/bpp-mcp`, `repo_name: iplweb/bpp-mcp`,
  `edit_uri: edit/main/docs/`.
- `site_url: https://iplweb.github.io/bpp-mcp/`, `site_name: bpp-mcp`.
- `exclude_docs: |` z `superpowers/` — specy brainstormingu **nie** trafiają na
  publiczną stronę.
- `nav`: jawna, zgodna ze strukturą z §3.

## 5. CI — `.github/workflows/docs.yml`

- `on`: `push` na `main` (paths: `docs/**`, `mkdocs.yml`,
  `.github/workflows/docs.yml`) + `workflow_dispatch`.
- `permissions`: `contents: read`, `pages: write`, `id-token: write`.
- `concurrency`: group `pages`, `cancel-in-progress: false`.
- **job `build`**: `actions/checkout` → `astral-sh/setup-uv` (**pinowane po SHA**,
  identycznie jak w `tests.yml`) → `uv sync --extra docs` →
  `uv run mkdocs build --strict` → `actions/upload-pages-artifact` (z `site/`).
- **job `deploy`**: `environment: github-pages`, `actions/deploy-pages`.
- Wszystkie akcje **pinowane po SHA** (spójnie z polityką bezpieczeństwa repo).

## 6. `pyproject.toml`

Dodać extra `docs`:

```toml
[project.optional-dependencies]
docs = [
    "mkdocs-material>=9.5",
    "pymdown-extensions>=10",
]
```

Lokalny podgląd: `uv run --extra docs mkdocs serve`.

## 7. Nowe README (~60–70 linii)

- Tytuł `# bpp-mcp` + badge `tests` + **nowy badge `docs`** (link do Pages).
- 2 akapity: co to jest / dlaczego MCP (skrót z obecnego README).
- **Quick start**: jedna komenda `uvx --from git+https://github.com/iplweb/bpp-mcp bpp-mcp`.
- Wyraźny link: **📖 Pełna dokumentacja → https://iplweb.github.io/bpp-mcp/**.
- Licencja.
- Cała reszta (konfiguracja, instalacja, OAuth, per-klient, narzędzia, DjangoQL,
  rozwój) **usunięta z README** i przeniesiona do `docs/`.

## 8. Zweryfikowane fakty per-klient (2026-07-24)

Źródło prawdy dla stron w `klienci/`. Wszystkie klienty stdio wywołują:
`command=uvx`, `args=["--from","git+https://github.com/iplweb/bpp-mcp","bpp-mcp"]`,
env `BPP_BASE_URL=https://bpp.umlub.pl`.

| Klient | Transport | Klucz / miejsce configu | Oficjalne docs |
|---|---|---|---|
| **Claude Desktop** | stdio | `mcpServers` w `claude_desktop_config.json` (macOS `~/Library/Application Support/Claude/`, Windows `%APPDATA%\Claude\`). **Brak oficjalnego buildu Linux** → kieruj na Claude Code. Menu Claude → Settings → Developer → Edit Config. Restart wymagany. | modelcontextprotocol.io/docs/develop/connect-local-servers ; support.claude.com/.../10949351 |
| **Claude Code** | stdio | `claude mcp add --transport stdio --env BPP_BASE_URL=... bpp-mcp -- uvx ...`. **Gotcha:** nie dawać nazwy zaraz po `--env`; `--` obowiązkowe. Scopes: local/project(`.mcp.json`)/user. | code.claude.com/docs/en/mcp ; docs.claude.com/en/docs/claude-code/cli-reference |
| **ChatGPT** | **HTTP only** | **Nie obsługuje stdio.** Wymaga `bpp-mcp --http` pod **publicznym HTTPS URL** (host lub tunel: ngrok/Cloudflare/OpenAI Secure MCP Tunnel). Settings → Apps & Connectors → Advanced → **Developer mode** → Create → URL `https://host/mcp`. Plany: Plus/Pro (Free nie); Business/Enterprise/Edu admin-gated. „connectors"→„apps" od 2025-12-17. | help.openai.com/.../12584461 ; developers.openai.com/apps-sdk/deploy/connect-chatgpt ; developers.openai.com/api/docs/mcp |
| **OpenCode** | stdio | Klucz `mcp` w `opencode.json` (global `~/.config/opencode/` lub projekt). `type:"local"`, **`command` = jedna tablica** (exe+args), env pod **`environment`** (nie `env`). | opencode.ai/docs/mcp-servers/ ; opencode.ai/docs/config/ |
| **DeepSeek** | (przez klienta) | **Brak własnej apki MCP.** DeepSeek = modele + API zgodne z OpenAI/Anthropic. Użyj klienta 3rd-party (rekomendacja: **Cherry Studio**) z kluczem DeepSeek + dodaj bpp-mcp (stdio uvx działa bez zmian). | api-docs.deepseek.com ; github.com/deepseek-ai/awesome-deepseek-agent/blob/main/docs/cherry_studio.md |
| **Cursor** | stdio | `mcpServers` w `~/.cursor/mcp.json` (global) lub `.cursor/mcp.json` (projekt). `command`+`args`+`env`. | cursor.com/docs/mcp ; docs.cursor.com/en/context/mcp |
| **VS Code + Copilot** | stdio | **Klucz `servers`** (NIE `mcpServers`!) w `.vscode/mcp.json` lub user `mcp.json` (cmd „MCP: Open User Configuration"). `type:"stdio"`, command/args/env. Tylko **Agent mode**. | code.visualstudio.com/docs/agent-customization/mcp-servers ; code.visualstudio.com/docs/copilot/customization/mcp-servers |
| **Windsurf** | stdio | `mcpServers` w `~/.codeium/windsurf/mcp_config.json`. command/args/env. UI: Cascade → MCP → „Add custom server"/„View raw config"; **naciśnij Refresh** po edycji. Limit **100 narzędzi** łącznie. | docs.windsurf.com/windsurf/cascade/mcp (→ docs.devin.ai/desktop/cascade/mcp) |
| **LM Studio** | stdio | `mcpServers` w `~/.lmstudio/mcp.json`. Program → Install → Edit mcp.json. command/args/env. Wymaga v0.3.17+. | lmstudio.ai/docs/app/plugins/mcp ; lmstudio.ai/blog/lmstudio-v0.3.17 |
| **Zed** | stdio | `context_servers` w settings.json (płaskie command/args/env). UI: Settings → AI → MCP Servers → Add Server → Add Local Server. | zed.dev/docs/ai/mcp ; zed.dev/docs/extensions/mcp-extensions |
| **inne** (`inne.md`) | stdio | Cline (`cline_mcp_settings.json`), Continue.dev (`.continue/mcpServers/` YAML, Agent mode), Goose (`goose configure` → Command-line Extension), Cherry Studio (Settings → MCP Servers → Add, Type STDIO), 5ire (Tools panel), JetBrains AI/Junie (Settings → Tools → AI Assistant → MCP), Warp (Warp Drive → MCP Servers → Add). | docs.cline.bot/mcp/configuring-mcp-servers ; docs.continue.dev/customize/deep-dives/mcp ; block.github.io/goose/docs/getting-started/using-extensions/ ; docs.cherryai.com.cn/advanced-basic/mcp/config ; github.com/nanbingxyz/5ire ; jetbrains.com/help/ai-assistant/mcp.html ; docs.warp.dev/agent-platform/capabilities/mcp/ |

**Wspólne pułapki do udokumentowania:**
- **PATH w apkach GUI:** `uvx` może nie być widoczne dla apki GUI — wtedy pełna
  ścieżka do `uvx` w `command` (snippet `path-caveat.md`).
- **Mirror-opposite schema:** OpenCode (`command` tablica + `environment`) vs
  Cursor/reszta (`command`+`args`+`env`) — nie kopiować 1:1.
- **VS Code:** klucz `servers`, nie `mcpServers`.

## 9. Testowanie / weryfikacja

- `uv run --extra docs mkdocs build --strict` przechodzi bez ostrzeżeń
  (strict wyłapie martwe linki wewnętrzne, brakujące pliki nav, złe snippety).
- `uv run --extra docs mkdocs serve` — lokalny podgląd renderuje się poprawnie.
- Lint linków wewnętrznych: `--strict` wystarcza dla linków wewn.; linki
  zewnętrzne (do docs klientów) sprawdzone ręcznie przez agentów researchowych.
- CI: workflow `docs.yml` zielony; po merge do `main` strona pod
  `https://iplweb.github.io/bpp-mcp/`.
- README: `mkdocs`/`ruff` nie dotyczą; sprawdzić ręcznie, że linki i badge działają.

## 10. Kroki ręczne

- **GitHub Pages** — *Settings → Pages → Source: GitHub Actions* — **zrobione
  przez użytkownika** ✅.

## 11. Poza zakresem (YAGNI)

- Wersjonowanie dokumentacji (mike) — nie teraz.
- Wielojęzyczność (i18n) — tylko polski.
- Autodoc z docstringów (mkdocstrings) — API narzędzi opisujemy ręcznie tabelą.
- Osobne strony dla każdego klienta z `inne.md` — zostają zbiorczo.
- Custom domena — używamy `github.io`.
