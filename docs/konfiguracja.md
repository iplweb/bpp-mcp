# Konfiguracja

Serwer jest **wielo-instancyjny** — tę samą binarkę podłączasz do dowolnego
wdrożenia BPP przez zmienne środowiskowe.

## Zmienne środowiskowe

| Zmienna | Domyślnie | Opis |
|---|---|---|
| `BPP_BASE_URL` | `https://bpp.umlub.pl` | bazowy URL instancji BPP (API i issuer OAuth) |
| `BPP_BASIC_AUTH` | *(brak)* | opcjonalny `user:pass` (tylko raporty slotów, stdio) |
| `BPP_MCP_TRANSPORT` | `stdio` | `stdio` (anon) lub `http` (OAuth per-user) |
| `BPP_MCP_HTTP_HOST` | `127.0.0.1` | bind serwera HTTP (tryb `http`) |
| `BPP_MCP_HTTP_PORT` | `8000` | port serwera HTTP (tryb `http`) |
| `BPP_MCP_RESOURCE_URL` | `http://<host>:<port>/mcp` | pole `resource` w protected-resource-metadata |

## Wiele instancji BPP

Aby połączyć się z inną instancją, ustaw `BPP_BASE_URL` na jej adres. W
konfiguracji klienta MCP zmienne podajesz w bloku `env` (lub odpowiedniku danego
klienta) — patrz [Klienci MCP](klienci/index.md). Przykład dla Claude Desktop:

```json
{
  "mcpServers": {
    "bpp": {
      "command": "uvx",
      "args": ["--from", "git+https://github.com/iplweb/bpp-mcp", "bpp-mcp"],
      "env": { "BPP_BASE_URL": "https://twoja-instancja.example.pl" }
    }
  }
}
```

Możesz zdefiniować kilka wpisów (`bpp-umlub`, `bpp-inna`…) z różnymi
`BPP_BASE_URL`, każdy jako osobny serwer MCP.

!!! note "Transport"
    `BPP_MCP_TRANSPORT` oraz flaga `--http` sterują trybem pracy. Domyślnie
    `stdio` (anonimowo lub per-user po `bpp-mcp login`). Tryb `http` uruchamia
    serwer OAuth Resource Server — patrz [Uwierzytelnianie](uwierzytelnianie.md).
