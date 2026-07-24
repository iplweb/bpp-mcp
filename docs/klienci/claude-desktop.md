# Claude Desktop

Claude Desktop uruchamia lokalne serwery **stdio** zdefiniowane w pliku
`claude_desktop_config.json`.

--8<-- "docs/_snippets/env-block.md"

## Konfiguracja

1. Otwórz Claude Desktop → menu **Claude → Settings… → zakładka Developer →
   Edit Config** (utworzy plik, jeśli nie istnieje).
2. Wklej wpis serwera:

```json
{
  "mcpServers": {
    "bpp": {
      "command": "uvx",
      "args": ["bpp-mcp"],
      "env": {
        "BPP_BASE_URL": "https://bpp.twoja-uczelnia.pl"
      }
    }
  }
}
```

3. **Zrestartuj** Claude Desktop w całości (config wczytywany jest przy starcie).

## Lokalizacja pliku

=== "macOS"

    ```
    ~/Library/Application Support/Claude/claude_desktop_config.json
    ```

=== "Windows"

    ```
    %APPDATA%\Claude\claude_desktop_config.json
    ```

!!! warning "Linux"
    Claude Desktop nie ma oficjalnego buildu na Linux. Użytkownicy Linuksa mogą
    skorzystać z [Claude Code](claude-code.md).

--8<-- "docs/_snippets/path-caveat.md"

## Diagnostyka

Logi MCP: macOS `~/Library/Logs/Claude/mcp*.log`; Windows `%APPDATA%\Claude\logs\`
(m.in. `mcp-server-bpp.log` ze stderr serwera).

## Zobacz też

- Oficjalnie: [Connect to local MCP servers](https://modelcontextprotocol.io/docs/develop/connect-local-servers),
  [Getting started with local MCP servers on Claude Desktop](https://support.claude.com/en/articles/10949351-getting-started-with-local-mcp-servers-on-claude-desktop).
- [Uwierzytelnianie](../uwierzytelnianie.md) — logowanie per-user (`bpp-mcp login`).
