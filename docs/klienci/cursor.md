# Cursor

[Cursor](https://cursor.com) obsługuje lokalne serwery stdio przez plik
`mcp.json`.

--8<-- "docs/_snippets/env-block.md"

## Konfiguracja

Globalnie `~/.cursor/mcp.json` (wszystkie projekty) albo w projekcie
`.cursor/mcp.json`:

```json
{
  "mcpServers": {
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

Możesz dodać `"type": "stdio"` jako pierwszy klucz, by dokładnie odpowiadać
dokumentowanemu schematowi (jest wnioskowany, gdy jest `command`).

--8<-- "docs/_snippets/path-caveat.md"

## Zobacz też

- Oficjalnie: [Model Context Protocol](https://cursor.com/docs/mcp)
  ([nowsza ścieżka](https://docs.cursor.com/en/context/mcp)).
- [Uwierzytelnianie](../uwierzytelnianie.md) — logowanie per-user (`bpp-mcp login`).
