# LM Studio

[LM Studio](https://lmstudio.ai) obsługuje lokalne serwery stdio MCP (notacja jak
w Cursorze). Wymaga wersji **0.3.17+**.

--8<-- "docs/_snippets/env-block.md"

## Konfiguracja

W aplikacji: prawy panel → zakładka **Program → Install → Edit `mcp.json`**.
Plik:

=== "macOS / Linux"

    ```
    ~/.lmstudio/mcp.json
    ```

=== "Windows"

    ```
    %USERPROFILE%\.lmstudio\mcp.json
    ```

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

--8<-- "docs/_snippets/path-caveat.md"

## Zobacz też

- Oficjalnie: [Use MCP Servers](https://lmstudio.ai/docs/app/plugins/mcp),
  [MCP w LM Studio (blog v0.3.17)](https://lmstudio.ai/blog/lmstudio-v0.3.17).
- [Uwierzytelnianie](../uwierzytelnianie.md) — logowanie per-user (`bpp-mcp login`).
