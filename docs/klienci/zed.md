# Zed

[Zed](https://zed.dev) obsługuje serwery MCP jako **context servers** —
konfigurowane w `settings.json` lub przez UI.

--8<-- "docs/_snippets/env-block.md"

## Konfiguracja

Otwórz ustawienia (`zed: open settings file`) i dodaj:

```json
{
  "context_servers": {
    "bpp": {
      "command": "uvx",
      "args": ["--from", "git+https://github.com/iplweb/bpp-mcp", "bpp-mcp"],
      "env": {
        "BPP_BASE_URL": "https://bpp.umlub.pl"
      }
    }
  }
}
```

Alternatywnie z UI: **Settings → AI → MCP Servers → Add Server → Add Local
Server**. Zielona kropka oznacza aktywny serwer.

--8<-- "docs/_snippets/path-caveat.md"

## Zobacz też

- Oficjalnie: [Model Context Protocol](https://zed.dev/docs/ai/mcp),
  [MCP Server Extensions](https://zed.dev/docs/extensions/mcp-extensions).
- [Uwierzytelnianie](../uwierzytelnianie.md) — logowanie per-user (`bpp-mcp login`).
