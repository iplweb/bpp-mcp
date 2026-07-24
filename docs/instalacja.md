# Instalacja

## Wymagania

- **Python 3.10+** (obsługiwane 3.10–3.13).
- **[uv](https://docs.astral.sh/uv/)** — rekomendowany sposób uruchamiania
  (zapewnia `uvx`). Alternatywnie `pip`.

Instalacja `uv` (jeśli nie masz):

=== "macOS / Linux"

    ```bash
    curl -LsSf https://astral.sh/uv/install.sh | sh
    ```

=== "Windows (PowerShell)"

    ```powershell
    powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
    ```

Szczegóły: [dokumentacja instalacji uv](https://docs.astral.sh/uv/getting-started/installation/).

## Najprościej: `uvx` z PyPI

Pakiet jest na [PyPI](https://pypi.org/project/bpp-mcp/). `uvx` pobiera go do
własnego cache'a i uruchamia w odizolowanym środowisku — nic nie ląduje w Twoim
systemowym Pythonie:

--8<-- "docs/_snippets/uvx-cmd.md"

To ta sama komenda, którą wpisujesz w konfiguracji klienta MCP
(patrz [Klienci MCP](klienci/index.md)).

!!! note "Zmienna `BPP_BASE_URL`"
    **Wymagana** (bez wartości domyślnej) — wskazuje instancję BPP, z którą łączy
    się serwer. Podmień `https://bpp.twoja-uczelnia.pl` na adres **swojej**
    instancji. Bez niej serwer nie wystartuje. Pełna lista zmiennych:
    [Konfiguracja](konfiguracja.md).

## Na stałe: `uv tool install` / `pip`

Jeśli wolisz mieć komendę `bpp-mcp` na stałe w `PATH`:

```bash
uv tool install bpp-mcp        # albo: pip install bpp-mcp
BPP_BASE_URL=https://bpp.twoja-uczelnia.pl bpp-mcp
```

Aktualizacja: `uv tool upgrade bpp-mcp` (przy `uvx` wystarczy `uvx bpp-mcp@latest`).

## Wersja rozwojowa (prosto z gita)

Niewydany kod z czubka gałęzi `main` — dostajesz zmiany przed wydaniem, ale też
przed ich przetestowaniem w praktyce. Do normalnego użycia weź wersję z PyPI.

```bash
BPP_BASE_URL=https://bpp.twoja-uczelnia.pl \
  uvx --from git+https://github.com/iplweb/bpp-mcp bpp-mcp
```

## Weryfikacja

Serwer stdio nie ma „ekranu powitalnego" — czeka na klienta MCP na standardowym
wejściu/wyjściu. Szybki test, że binarka się uruchamia i widzi swoje komendy
(`--help` nie wymaga `BPP_BASE_URL`):

```bash
uvx bpp-mcp --help
```

Do faktycznego użycia podłącz serwer do klienta MCP — patrz
[Klienci MCP](klienci/index.md).

!!! tip "Logowanie per-user"
    Domyślnie serwer działa **anonimowo** (dane publiczne). Aby korzystać z
    uprawnień zalogowanego konta BPP — patrz [Uwierzytelnianie](uwierzytelnianie.md).
