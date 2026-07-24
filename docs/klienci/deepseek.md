# DeepSeek

!!! note "DeepSeek nie ma własnej aplikacji z klientem MCP"
    DeepSeek to **dostawca modeli** (oraz API zgodne z OpenAI/Anthropic), a nie
    host MCP. Żeby używać `bpp-mcp` „z DeepSeekiem", uruchom **klient MCP innej
    firmy** i ustaw w nim DeepSeeka jako model (przez klucz API).

## Rekomendowana droga: Cherry Studio + DeepSeek

[Cherry Studio](https://cherry-ai.com) to desktopowy klient MCP, który pozwala
wybrać dostawcę modelu i dodać serwery MCP. Ta kombinacja jest udokumentowana
przez samych autorów DeepSeeka.

1. **Ustaw model DeepSeek.** Cherry Studio → **Settings → Model Provider →
   DeepSeek**, wklej **klucz API DeepSeek**, host `https://api.deepseek.com`,
   pobierz modele (np. `deepseek-chat`, `deepseek-reasoner`).
2. **Dodaj serwer `bpp-mcp`.** Kroki dodania serwera MCP w Cherry Studio opisano
   na stronie [Inne klienty → Cherry Studio](inne.md#cherry-studio). Ponieważ
   Cherry Studio uruchamia serwer **lokalnie**, działa domyślna komenda stdio:

--8<-- "docs/_snippets/uvx-cmd.md"

Po skonfigurowaniu każda rozmowa prowadzona modelem DeepSeek może korzystać z
narzędzi `bpp-mcp`.

!!! tip "Inne klienty z DeepSeekiem"
    Podobnie zadziałają **Cline**, **5ire** czy **Continue** — wszystkie
    pozwalają ustawić endpoint zgodny z OpenAI (DeepSeek) i dodać serwer MCP.
    Patrz [Inne klienty](inne.md).

## Zobacz też

- Oficjalnie: [DeepSeek API docs](https://api-docs.deepseek.com/),
  [DeepSeek: integracja z Cherry Studio](https://github.com/deepseek-ai/awesome-deepseek-agent/blob/main/docs/cherry_studio.md).
- [Uwierzytelnianie](../uwierzytelnianie.md) — logowanie per-user (`bpp-mcp login`).
