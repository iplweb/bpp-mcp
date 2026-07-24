# Inne klienty

Poniższe klienty również obsługują lokalne serwery **stdio** — `bpp-mcp`
podłączysz tą samą komendą, różni się tylko miejsce konfiguracji:

--8<-- "docs/_snippets/uvx-cmd.md"

W formularzach/JSON-ach wpisujesz zwykle: **command** = `uvx`, **args** =
`["bpp-mcp"]`, **env** =
`{ "BPP_BASE_URL": "https://bpp.twoja-uczelnia.pl" }`.

--8<-- "docs/_snippets/path-caveat.md"

## Cline

Rozszerzenie VS Code. Kliknij ikonę **MCP Servers** na pasku Cline → **Configure**
(edytuje `cline_mcp_settings.json` z `command`/`args`/`env`, `type: stdio`).

- Docs: [Configuring MCP Servers](https://docs.cline.bot/mcp/configuring-mcp-servers).
- Uwaga: auto-zatwierdzanie narzędzi jest domyślnie wyłączone — każde wywołanie
  potwierdzasz, dopóki nie włączysz.

## Continue.dev

Rozszerzenie VS Code / JetBrains. Dodaj plik YAML w `.continue/mcpServers/`
(`type: stdio`, `command`, `args`) lub blok `mcpServers` w konfiguracji.

- Docs: [MCP](https://docs.continue.dev/customize/deep-dives/mcp).
- Uwaga: narzędzia MCP działają tylko w **trybie Agent**.

## Goose

Agent Blocka. `goose configure` → **Add Extension → Command-line Extension**
(Desktop: **Extensions → Add custom extension**); zapis w
`~/.config/goose/config.yaml`.

- Docs: [Using Extensions](https://block.github.io/goose/docs/getting-started/using-extensions/).
- Uwaga: serwery stdio nazywane są „Command-line Extensions"; domyślny timeout 300 s.

## Cherry Studio

Desktopowy klient MCP. **Settings → MCP Servers → + Add Server**, ustaw
**Type = STDIO**, **Command = `uvx`**, uzupełnij Args i Env.

- Docs: [MCP config](https://docs.cherryai.com.cn/advanced-basic/mcp/config).
- Uwaga: aplikacja ma wbudowane `uv`/`bun`, które potrafi doinstalować sama. Dobra
  droga do użycia `bpp-mcp` [z modelem DeepSeek](deepseek.md).

## 5ire

Desktopowy klient MCP. Prawy panel **Tools** → dodaj narzędzie (command/args/env);
5ire zapisuje konfigurację sam.

- Docs: [5ire (GitHub)](https://github.com/nanbingxyz/5ire).
- Uwaga: głównie stdio; nowsze wersje sięgają serwerów zdalnych przez `mcp-remote`.

## JetBrains AI Assistant / Junie

W IDE JetBrains: **Settings → Tools → AI Assistant → Model Context Protocol (MCP)
→ Add** (wklej JSON `mcpServers` albo wypełnij pola stdio). Junie współdzieli tę
konfigurację.

- Docs: [MCP (AI Assistant)](https://www.jetbrains.com/help/ai-assistant/mcp.html).
- Uwaga: wymaga wtyczki/subskrypcji AI Assistant oraz IDE 2025.x+.

## Warp

Terminal Warp. **Warp Drive → MCP Servers → + Add**, wklej JSON z
`command`/`args`/`env`.

- Docs: [MCP](https://docs.warp.dev/agent-platform/capabilities/mcp/).
- Uwaga: ustaw `working_directory`, jeśli używasz ścieżek względnych.

## Zobacz też

- [Uwierzytelnianie](../uwierzytelnianie.md) — logowanie per-user (`bpp-mcp login`).
