!!! warning "`uvx` musi być widoczne dla aplikacji"
    Aplikacje uruchamiane z GUI (Claude Desktop, Cursor, LM Studio, Zed…) często
    mają okrojony `PATH` i mogą nie znaleźć `uvx`. Jeśli serwer się nie startuje,
    podaj **pełną ścieżkę** do `uvx` w polu `command` (np. `~/.local/bin/uvx`
    albo ścieżkę z Homebrew). Lokalizację sprawdzisz przez `which uvx`
    (Windows: `where uvx`).
