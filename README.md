# bpp-mcp

[![PyPI](https://img.shields.io/pypi/v/bpp-mcp.svg)](https://pypi.org/project/bpp-mcp/)
[![Python](https://img.shields.io/pypi/pyversions/bpp-mcp.svg)](https://pypi.org/project/bpp-mcp/)
[![tests](https://github.com/iplweb/bpp-mcp/actions/workflows/tests.yml/badge.svg)](https://github.com/iplweb/bpp-mcp/actions/workflows/tests.yml)
[![docs](https://github.com/iplweb/bpp-mcp/actions/workflows/docs.yml/badge.svg)](https://github.com/iplweb/bpp-mcp/actions/workflows/docs.yml)

> ⚠️ **W większości przypadków nie potrzebujesz tego pakietu.** Aktualne wersje BPP
> mają serwer MCP **wbudowany** — nic nie instalujesz, tylko dopisujesz `/mcp`
> do adresu swojej bibliografii:
>
> - `https://bpp.twoja-uczelnia.pl/mcp` — dostęp publiczny, bez logowania;
>   działa z każdym klientem obsługującym zdalne serwery MCP,
> - `https://bpp.twoja-uczelnia.pl/mcp/auth` — z logowaniem kontem BPP, także
>   do danych niepublicznych.
>
> Otwórz `/mcp` w przeglądarce — znajdziesz tam gotową instrukcję podłączenia
> asystenta AI. Opis: **[bpp.iplweb.pl/bpp-ai](https://bpp.iplweb.pl/bpp-ai)**.

Serwer [MCP](https://modelcontextprotocol.io) dla **API BPP**
([Bibliografia Publikacji Pracowników](https://bpp.iplweb.pl)) jako osobny
program, uruchamiany na Twoim komputerze. Wystawia API BPP (`/api/v1/`) jako
zestaw starannie dobranych, typowanych narzędzi dla Claude Desktop, Claude Code,
ChatGPT i innych klientów MCP — ten sam zestaw, który jest pod adresem `/mcp`.
Dokumentacja online: **[iplweb.github.io/bpp-mcp](https://iplweb.github.io/bpp-mcp/)**.

Zamiast żmudnego chodzenia po hyperlinkach REST-owych (publikacja → autorzy →
jednostka → …), serwer robi to za agenta: rozwija relacje, auto-follow-uje
paginację i zwraca gotowe, zagnieżdżone obiekty. `pobierz_rekord` zwraca jeden
obiekt z rozwiniętymi autorami (nazwisko jak wydrukowane), źródłem i
streszczeniami — zamiast kilkunastu żądań REST.

## Kiedy sięgnąć po bpp-mcp

Samodzielny `bpp-mcp` ma sens tylko wtedy, gdy wbudowany serwer `/mcp` Ci nie
wystarcza:

- **Twoja instalacja BPP nie ma jeszcze adresu `/mcp`.** `bpp-mcp` łączy się
  z bibliografią przez jej API, więc zadziała także na starszych wersjach.
- **Potrzebujesz najnowszych narzędzi od razu.** Nowe funkcje trafiają najpierw
  do `bpp-mcp`, a do serwera wbudowanego w BPP — z kolejnym wydaniem systemu.
- **Twój klient nie obsługuje zdalnych serwerów MCP.** Część programów
  uruchamia serwery MCP wyłącznie lokalnie (stdio) — `bpp-mcp` działa właśnie
  tak.
- **Rozwijasz lub testujesz narzędzia MCP dla BPP** lokalnie, zanim trafią do
  systemu.

Jeśli żaden z tych punktów Cię nie dotyczy — użyj `/mcp` i pomiń resztę tego
dokumentu.

## 📖 Dokumentacja

Pełna dokumentacja (instalacja, konfiguracja, uwierzytelnianie, podłączanie do
klientów MCP, narzędzia, DjangoQL):

**→ [iplweb.github.io/bpp-mcp](https://iplweb.github.io/bpp-mcp/)**

## Szybki start

[![Zainstaluj w Claude Desktop](https://img.shields.io/badge/Zainstaluj_w-Claude_Desktop-D97757?style=for-the-badge&logo=anthropic&logoColor=white)](https://github.com/iplweb/bpp-mcp/releases/latest/download/bpp-mcp.mcpb)
[![Zainstaluj w Cursor](https://img.shields.io/badge/Zainstaluj_w-Cursor-000000?style=for-the-badge&logo=cursor&logoColor=white)](https://cursor.com/en/install-mcp?name=bpp-mcp&config=eyJjb21tYW5kIjoidXZ4IiwiYXJncyI6WyJicHAtbWNwIl0sImVudiI6eyJCUFBfQkFTRV9VUkwiOiIifX0=)
[![Zainstaluj w VS Code](https://img.shields.io/badge/Zainstaluj_w-VS_Code-0098FF?style=for-the-badge&logo=visualstudiocode&logoColor=white)](https://vscode.dev/redirect?url=vscode:mcp/install?%7B%22name%22%3A%22bpp-mcp%22%2C%22command%22%3A%22uvx%22%2C%22args%22%3A%5B%22bpp-mcp%22%5D%2C%22env%22%3A%7B%22BPP_BASE_URL%22%3A%22%22%7D%7D)

> Instalator Claude Desktop pyta o adres instancji BPP. Linki do Cursora i VS
> Code niosą `BPP_BASE_URL` puste celowo — wpisz własny adres (np.
> `https://bpp.umlub.pl`). Bez niego serwer nie wystartuje, i tak ma być: każde
> wdrożenie BPP to inna uczelnia, więc zaszyty host pokazywałby po cichu cudzą
> bibliografię jako własną.

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

## Demo — przykładowe zapytania

Podłączony do asystenta AI — przez wbudowany adres `/mcp` albo przez `bpp-mcp` —
serwer pozwala pytać o dane BPP zwykłym zdaniem, bez znajomości struktury bazy
i bez jednego eksportu do arkusza. Dwa przykłady wraz z odpowiedziami, jakie
zwraca asystent:

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
