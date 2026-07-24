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

## Najprościej: `uvx` prosto z gita

Nie wymaga ręcznej instalacji pakietu — `uvx` pobiera i uruchamia serwer w
izolowanym środowisku:

--8<-- "docs/_snippets/uvx-cmd.md"

To ta sama komenda, którą wpisujesz w konfiguracji klienta MCP
(patrz [Klienci MCP](klienci/index.md)).

## Alternatywnie: `pip`

```bash
pip install "git+https://github.com/iplweb/bpp-mcp"
bpp-mcp
```

## Weryfikacja

Serwer stdio nie ma „ekranu powitalnego" — czeka na klienta MCP na standardowym
wejściu/wyjściu. Szybki test, że binarka się uruchamia i widzi swoje komendy:

```bash
uvx --from git+https://github.com/iplweb/bpp-mcp bpp-mcp --help
```

Do faktycznego użycia podłącz serwer do klienta MCP — patrz
[Klienci MCP](klienci/index.md).

!!! tip "Logowanie per-user"
    Domyślnie serwer działa **anonimowo** (dane publiczne). Aby korzystać z
    uprawnień zalogowanego konta BPP — patrz [Uwierzytelnianie](uwierzytelnianie.md).
