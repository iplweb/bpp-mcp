# bpp-mcp

[![PyPI](https://img.shields.io/pypi/v/bpp-mcp.svg)](https://pypi.org/project/bpp-mcp/)
[![Python](https://img.shields.io/pypi/pyversions/bpp-mcp.svg)](https://pypi.org/project/bpp-mcp/)
[![tests](https://github.com/iplweb/bpp-mcp/actions/workflows/tests.yml/badge.svg)](https://github.com/iplweb/bpp-mcp/actions/workflows/tests.yml)
[![docs](https://github.com/iplweb/bpp-mcp/actions/workflows/docs.yml/badge.svg)](https://github.com/iplweb/bpp-mcp/actions/workflows/docs.yml)

Serwer [MCP](https://modelcontextprotocol.io) dla **API BPP**
([Bibliografia Publikacji Pracowników](https://bpp.iplweb.pl)). Wystawia
read-only, anonimowe API BPP (`/api/v1/`) jako
zestaw starannie dobranych, typowanych narzędzi dla Claude Desktop, Claude Code,
ChatGPT i innych klientów MCP.

Zamiast żmudnego chodzenia po hyperlinkach REST-owych (publikacja → autorzy →
jednostka → …), serwer robi to za agenta: rozwija relacje, auto-follow-uje
paginację i zwraca gotowe, zagnieżdżone obiekty. `pobierz_rekord` zwraca jeden
obiekt z rozwiniętymi autorami (nazwisko jak wydrukowane), źródłem i
streszczeniami — zamiast kilkunastu żądań REST.

## Szybki start

`bpp-mcp` to serwer MCP działający po stdio — **nie uruchamiasz go samodzielnie**
w terminalu (odpalony ręcznie tylko czeka w ciszy na klienta na standardowym
wejściu). „Uruchomienie" polega na **dodaniu serwera do klienta MCP**, który
startuje go za Ciebie i przez którego z nim rozmawiasz. Pakiet jest na
[PyPI](https://pypi.org/project/bpp-mcp/) — przez [uv](https://docs.astral.sh/uv/)
klient pobierze go i odpali bez instalacji (komenda `uvx bpp-mcp`).

**1. Dodaj serwer do klienta.** Najkrócej — Claude Code. W **terminalu** (nie
w sesji Claude Code) wpisz, podmieniając adres na swoją instancję BPP:

```bash
claude mcp add bpp --transport stdio --env BPP_BASE_URL=https://bpp.twoja-uczelnia.pl \
  -- uvx bpp-mcp
```

- Nazwa serwera (`bpp`) musi stać **przed** `--env` (flaga jest zachłanna —
  pochłania kolejne `KEY=value`), a `--` oddziela flagi `claude` od komendy
  uruchamiającej serwer (`uvx bpp-mcp`).
- Dopisz `--scope user`, by serwer był dostępny we wszystkich Twoich projektach
  (domyślnie tylko w bieżącym).
- Sprawdź, że wstał: `claude mcp list` w terminalu albo `/mcp` w sesji Claude Code.

Pełny opis (scope, równoważny wpis w `.mcp.json`):
[Claude Code](https://iplweb.github.io/bpp-mcp/klienci/claude-code/). Claude
Desktop i pozostałe klienty (ChatGPT, Cursor, VS Code, Windsurf, LM Studio, Zed…)
mają gotowe, sprawdzone wpisy tutaj:
**[Klienci MCP](https://iplweb.github.io/bpp-mcp/klienci/)**.

**2. Pytaj asystenta o dane BPP.** To wszystko — zwykłym zdaniem, przykłady
w sekcji **Demo** niżej.

> **`BPP_BASE_URL` jest wymagany** (bez wartości domyślnej) — wskazuje instancję
> BPP, z którą łączy się serwer. Inne sposoby instalacji (`uv tool install`,
> `pip`, wersja rozwojowa z gita):
> [Instalacja](https://iplweb.github.io/bpp-mcp/instalacja/).

## 📖 Dokumentacja

Pełna dokumentacja (instalacja, konfiguracja, uwierzytelnianie, podłączanie do
klientów MCP, narzędzia, DjangoQL):

**→ [iplweb.github.io/bpp-mcp](https://iplweb.github.io/bpp-mcp/)**

## Demo — przykładowe zapytania

Podłączony do asystenta AI, serwer pozwala pytać o dane BPP zwykłym zdaniem — bez
znajomości struktury bazy i bez jednego eksportu do arkusza. Dwa przykłady wraz
z odpowiedziami, jakie zwraca asystent:

> **Przygotuj sylwetkę naukową prof. [Nazwisko]** na podstawie całego dorobku
> w BPP: obszary badań, najważniejsze publikacje, główne czasopisma, dynamikę
> w czasie i pozycję autorską. Złóż to w estetyczną, gotową do druku kartę.

![Przykładowa sylwetka naukowca wygenerowana przez asystenta AI](https://bpp.iplweb.pl/images/bpp-ai/sylwetka_naukowca.png)

> **Złóż sylwetkę Kliniki Nefrologii:** dorobek w liczbach, czołowych autorów,
> najważniejsze prace, dynamikę w czasie i wstępną gotowość do ewaluacji. Gotowe
> do druku.

![Przykładowa sylwetka jednostki wygenerowana przez asystenta AI](https://bpp.iplweb.pl/images/bpp-ai/sylwetka_jednostki.png)

Więcej przykładów i opis możliwości:
[bpp.iplweb.pl/bpp-ai](https://bpp.iplweb.pl/bpp-ai).

## Licencja

MIT — IPLWeb / Michał Pasternak. Patrz [LICENSE](LICENSE).
