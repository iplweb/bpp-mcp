# Windsurf

[Windsurf](https://windsurf.com) (Cascade) obsługuje lokalne serwery stdio przez
plik `mcp_config.json`.

--8<-- "docs/_snippets/env-block.md"

## Konfiguracja

Plik `mcp_config.json`:

=== "macOS / Linux"

    ```
    ~/.codeium/windsurf/mcp_config.json
    ```

=== "Windows"

    ```
    %USERPROFILE%\.codeium\windsurf\mcp_config.json
    ```

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

Możesz też otworzyć config z UI: **panel Cascade → ikona MCP/plugins** (prawy
górny róg), albo **Settings → Cascade → MCP Servers → „Add custom server" /
„View raw config"**.

!!! warning "Naciśnij „Refresh" po edycji"
    Po ręcznej edycji `mcp_config.json` kliknij przycisk **Refresh**, aby Windsurf
    wczytał zmiany. Uwaga na **limit 100 narzędzi** łącznie ze wszystkich serwerów —
    wyłączaj nieużywane.

--8<-- "docs/_snippets/path-caveat.md"

## Zobacz też

- Oficjalnie: [MCP w Cascade](https://docs.windsurf.com/windsurf/cascade/mcp).
- [Uwierzytelnianie](../uwierzytelnianie.md) — logowanie per-user (`bpp-mcp login`).
