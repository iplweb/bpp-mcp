# Klienci MCP

`bpp-mcp` podłączysz do dowolnego klienta obsługującego protokół
[MCP](https://modelcontextprotocol.io). Poniżej gotowe instrukcje dla
najpopularniejszych.

--8<-- "docs/_snippets/stdio-vs-http.md"

## Który klient jak?

| Klient | Transport | Uwagi |
|---|---|---|
| [Claude Desktop](claude-desktop.md) | stdio | brak oficjalnego buildu na Linux |
| [Claude Code](claude-code.md) | stdio | CLI, `claude mcp add` |
| [ChatGPT](chatgpt.md) | **HTTP** | tylko zdalne serwery — wymaga `--http` pod publicznym URL |
| [OpenCode](opencode.md) | stdio | schemat `command`-tablica + `environment` |
| [DeepSeek](deepseek.md) | (przez klienta) | brak własnej apki MCP — przez np. Cherry Studio |
| [Cursor](cursor.md) | stdio | `~/.cursor/mcp.json` |
| [VS Code (Copilot)](vscode-copilot.md) | stdio | klucz `servers`, Agent mode |
| [Windsurf](windsurf.md) | stdio | limit 100 narzędzi, „Refresh" po edycji |
| [LM Studio](lm-studio.md) | stdio | `~/.lmstudio/mcp.json`, v0.3.17+ |
| [Zed](zed.md) | stdio | `context_servers` |
| [Inne klienty](inne.md) | stdio | Cline, Continue.dev, Goose, Cherry Studio, 5ire, JetBrains, Warp |

## Wspólny wzorzec (stdio)

Prawie każdy klient stdio uruchamia serwer tą samą komendą:

--8<-- "docs/_snippets/uvx-cmd.md"

…różni się jedynie **miejscem i formatem** konfiguracji. W większości sprowadza
się to do trójki:

- **command** — `uvx`
- **args** — `["--from", "git+https://github.com/iplweb/bpp-mcp", "bpp-mcp"]`
- **env** — `{ "BPP_BASE_URL": "https://bpp.umlub.pl" }`

--8<-- "docs/_snippets/path-caveat.md"

!!! warning "Uwaga na różnice schematów"
    Nie kopiuj konfiguracji 1:1 między klientami. Np. **OpenCode** używa jednej
    tablicy `command` (razem z argumentami) i klucza `environment`, a **VS Code**
    używa klucza `servers` zamiast `mcpServers`. Trzymaj się strony danego klienta.
