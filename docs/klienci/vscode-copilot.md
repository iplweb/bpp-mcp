# VS Code (GitHub Copilot)

Visual Studio Code obsługuje lokalne serwery stdio MCP; ich narzędzia są używane
w **trybie Agent** GitHub Copilota (Chat → dropdown trybu → **Agent**).

--8<-- "docs/_snippets/env-block.md"

!!! warning "Klucz to `servers`, nie `mcpServers`"
    W konfiguracji VS Code top-level to **`servers`** (inaczej niż w Cursorze czy
    Claude). Częsta pomyłka przy kopiowaniu.

## Konfiguracja

W projekcie `.vscode/mcp.json` (albo w konfiguracji użytkownika przez komendę
**„MCP: Open User Configuration"**):

```json
{
  "servers": {
    "bpp": {
      "type": "stdio",
      "command": "uvx",
      "args": ["bpp-mcp"],
      "env": {
        "BPP_BASE_URL": "https://bpp.twoja-uczelnia.pl"
      }
    }
  }
}
```

Możesz też dodać serwer przez paletę: **„MCP: Add Server"**, albo z CLI:
`code --add-mcp "{...}"`.

--8<-- "docs/_snippets/path-caveat.md"

!!! note "Tryb Agent i zaufanie"
    Narzędzia MCP działają wyłącznie w **trybie Agent**; przy pierwszym starcie
    serwera pojawia się prośba o zaufanie. Autodetekcja serwerów z innych apek
    jest domyślnie wyłączona (`chat.mcp.discovery.enabled`). W środowiskach
    firmowych MCP może być wyłączone polityką.

## Zobacz też

- Oficjalnie: [Use MCP servers in VS Code](https://code.visualstudio.com/docs/agent-customization/mcp-servers),
  [MCP servers (Copilot)](https://code.visualstudio.com/docs/copilot/customization/mcp-servers).
- [Uwierzytelnianie](../uwierzytelnianie.md) — logowanie per-user (`bpp-mcp login`).
