# bpp-mcp

Serwer [MCP](https://modelcontextprotocol.io) dla **API BPP** (Bibliografia
Publikacji Pracowników). Wystawia read-only, anonimowe API BPP (`/api/v1/`) jako
zestaw kuratorowanych, typowanych narzędzi dla Claude Desktop, Claude Code,
ChatGPT i innych klientów MCP.

Zamiast żmudnego chodzenia po hyperlinkach REST-owych (publikacja → autorzy →
jednostka → …), serwer robi to za agenta: rozwija relacje, auto-follow-uje
paginację i zwraca gotowe, zagnieżdżone obiekty.

## Dlaczego MCP, a nie samo API?

API BPP jest **hyperlinked** — relacje to URL-e, nie zagnieżdżone dane. Pobranie
jednego rekordu z autorami i źródłem to kilka–kilkanaście żądań. `bpp-mcp` ukrywa
tę złożoność: `pobierz_rekord` zwraca jeden obiekt z rozwiniętymi autorami
(nazwisko jak wydrukowane), źródłem i streszczeniami.

## Szybki start

Uruchomienie z [PyPI](https://pypi.org/project/bpp-mcp/) przez
[uv](https://docs.astral.sh/uv/):

--8<-- "docs/_snippets/uvx-cmd.md"

Serwer komunikuje się po stdio (standard MCP) — normalnie uruchamia go klient
MCP, nie użytkownik ręcznie. Zajrzyj do:

- [Instalacja](instalacja.md) — wymagania i sposoby instalacji.
- [Konfiguracja](konfiguracja.md) — zmienne środowiskowe, wiele instancji BPP.
- [Uwierzytelnianie](uwierzytelnianie.md) — tryby anonimowy, per-user (stdio) i
  OAuth (HTTP).
- [Klienci MCP](klienci/index.md) — jak podłączyć `bpp-mcp` do Twojego asystenta.
- [Narzędzia](narzedzia.md) — co serwer udostępnia.
- [DjangoQL](djangoql.md) — budowanie precyzyjnych zapytań.

## Licencja

MIT — IPLWeb / Michał Pasternak. Patrz
[LICENSE](https://github.com/iplweb/bpp-mcp/blob/main/LICENSE).
