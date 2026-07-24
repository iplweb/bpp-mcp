# bpp-mcp

[![PyPI](https://img.shields.io/pypi/v/bpp-mcp.svg)](https://pypi.org/project/bpp-mcp/)
[![Python](https://img.shields.io/pypi/pyversions/bpp-mcp.svg)](https://pypi.org/project/bpp-mcp/)
[![tests](https://github.com/iplweb/bpp-mcp/actions/workflows/tests.yml/badge.svg)](https://github.com/iplweb/bpp-mcp/actions/workflows/tests.yml)
[![docs](https://github.com/iplweb/bpp-mcp/actions/workflows/docs.yml/badge.svg)](https://github.com/iplweb/bpp-mcp/actions/workflows/docs.yml)

Serwer [MCP](https://modelcontextprotocol.io) dla **API BPP** (Bibliografia
Publikacji Pracowników). Wystawia read-only, anonimowe API BPP (`/api/v1/`) jako
zestaw kuratorowanych, typowanych narzędzi dla Claude Desktop, Claude Code,
ChatGPT i innych klientów MCP.

Zamiast żmudnego chodzenia po hyperlinkach REST-owych (publikacja → autorzy →
jednostka → …), serwer robi to za agenta: rozwija relacje, auto-follow-uje
paginację i zwraca gotowe, zagnieżdżone obiekty. `pobierz_rekord` zwraca jeden
obiekt z rozwiniętymi autorami (nazwisko jak wydrukowane), źródłem i
streszczeniami — zamiast kilkunastu żądań REST.

## 📖 Dokumentacja

Pełna dokumentacja (instalacja, konfiguracja, uwierzytelnianie, podłączanie do
klientów MCP, narzędzia, DjangoQL):

**→ [iplweb.github.io/bpp-mcp](https://iplweb.github.io/bpp-mcp/)**

## Szybki start

Pakiet jest na [PyPI](https://pypi.org/project/bpp-mcp/). Najprościej — bez
instalowania czegokolwiek na stałe, przez [uv](https://docs.astral.sh/uv/):

```bash
BPP_BASE_URL=https://bpp.twoja-uczelnia.pl uvx bpp-mcp
```

`BPP_BASE_URL` jest **wymagany** (bez wartości domyślnej) — wskazuje instancję
BPP, z którą łączy się serwer. Szczegóły instalacji (m.in. `uv tool install` /
`pip`, wersja rozwojowa z gita): [Instalacja](https://iplweb.github.io/bpp-mcp/instalacja/).

Serwer komunikuje się po stdio (standard MCP) — normalnie uruchamia go klient
MCP, nie użytkownik ręcznie. Jak podłączyć go do konkretnego asystenta
(Claude Desktop/Code, ChatGPT, Cursor, VS Code, Windsurf, LM Studio, Zed i inne):
**[Klienci MCP](https://iplweb.github.io/bpp-mcp/klienci/)**.

## Licencja

MIT — IPLWeb / Michał Pasternak. Patrz [LICENSE](LICENSE).
