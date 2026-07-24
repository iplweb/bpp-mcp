# OpenCode

[OpenCode](https://opencode.ai) obsługuje lokalne serwery stdio (nazywa je
„local"). Konfiguracja w `opencode.json`.

--8<-- "docs/_snippets/env-block.md"

!!! warning "Schemat inny niż w większości klientów"
    OpenCode łączy komendę i argumenty w **jedną tablicę `command`**, a zmienne
    środowiskowe trzyma pod kluczem **`environment`** (nie `env`). Nie kopiuj tu
    configu od Cursora/Claude.

## Konfiguracja

Globalnie `~/.config/opencode/opencode.json` albo w katalogu projektu
`opencode.json`:

```json
{
  "$schema": "https://opencode.ai/config.json",
  "mcp": {
    "bpp": {
      "type": "local",
      "command": ["uvx", "bpp-mcp"],
      "enabled": true,
      "environment": {
        "BPP_BASE_URL": "https://bpp.twoja-uczelnia.pl"
      }
    }
  }
}
```

- `type: "local"` — transport stdio (dla zdalnego: `"remote"` + `url`).
- `command` — jedna tablica: program **i** argumenty.
- `environment` — obiekt zmiennych (podstawianie wartości: `{env:NAME}`).
- `enabled: false` pozwala zdefiniować serwer, ale go wyłączyć.

--8<-- "docs/_snippets/path-caveat.md"

## Zobacz też

- Oficjalnie: [MCP servers](https://opencode.ai/docs/mcp-servers/),
  [Config](https://opencode.ai/docs/config/).
- [Uwierzytelnianie](../uwierzytelnianie.md) — logowanie per-user (`bpp-mcp login`).
