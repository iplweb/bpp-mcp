# Claude Code

Claude Code (CLI) dodaje serwery stdio komendą `claude mcp add`.

--8<-- "docs/_snippets/env-block.md"

## Dodanie serwera

```bash
claude mcp add bpp --transport stdio --env BPP_BASE_URL=https://bpp.twoja-uczelnia.pl \
  -- uvx bpp-mcp
```

!!! warning "Kolejność argumentów"
    Nazwa serwera (`bpp`) stoi **przed** flagą `--env`. `--env` jest zachłanne —
    pochłania kolejne pary `KEY=value` aż do następnej flagi lub `--`; gdyby nazwa
    stała **tuż po** wartości `--env`, zostałaby potraktowana jako kolejna zmienna
    i komenda by się rozjechała. Separator `--` (przed komendą serwera) jest
    **obowiązkowy** — oddziela flagi `claude` od komendy uruchamiającej serwer.

## Zakresy (scope)

| Scope | Widoczność | Zapis |
|---|---|---|
| `local` (domyślny) | tylko bieżący projekt, prywatnie | `~/.claude.json` |
| `project` | bieżący projekt, współdzielony przez repo | `.mcp.json` (w repo) |
| `user` | wszystkie Twoje projekty | `~/.claude.json` |

Dodaj `--scope user`, by serwer był dostępny wszędzie, albo `--scope project`, by
zacommitować go do repo (`.mcp.json`, przy pierwszym użyciu wymaga zgody).

Wpis równoważny w `.mcp.json` (scope `project`):

```json
{
  "mcpServers": {
    "bpp": {
      "command": "uvx",
      "args": ["bpp-mcp"],
      "env": { "BPP_BASE_URL": "https://bpp.twoja-uczelnia.pl" }
    }
  }
}
```

## Weryfikacja

```bash
claude mcp list          # połączone / błędy
claude mcp get bpp       # szczegóły
```

W sesji interaktywnej: `/mcp`.

## Zobacz też

- Oficjalnie: [Connect Claude Code to tools via MCP](https://code.claude.com/docs/en/mcp),
  [CLI reference](https://docs.claude.com/en/docs/claude-code/cli-reference).
- [Uwierzytelnianie](../uwierzytelnianie.md) — logowanie per-user (`bpp-mcp login`).
