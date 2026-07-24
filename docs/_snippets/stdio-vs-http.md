!!! info "stdio czy HTTP?"
    Domyślnie `bpp-mcp` działa jako **lokalny proces stdio** — klient uruchamia go
    sam komendą `uvx …`. To najprostszy wariant i działa w większości klientów.
    Tryb **HTTP/OAuth** (`bpp-mcp --http`) jest potrzebny tylko dla klientów, które
    przyjmują **zdalne** serwery MCP przez URL (np. ChatGPT) — patrz
    [Uwierzytelnianie](../uwierzytelnianie.md).
