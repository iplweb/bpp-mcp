# ChatGPT

!!! warning "ChatGPT obsługuje tylko **zdalne** serwery MCP (HTTPS)"
    ChatGPT **nie** uruchamia lokalnych serwerów stdio. Domyślna komenda
    `uvx … bpp-mcp` (stdio) tu **nie zadziała**. Musisz uruchomić `bpp-mcp` w
    trybie **HTTP** i wystawić go pod **publicznym adresem HTTPS**.

## Wymagania

- **Plan płatny.** Dodawanie własnych connectorów działa w Developer mode
  (Plus/Pro; w Business/Enterprise/Edu wymaga włączenia przez administratora).
  Plan Free nie jest obsługiwany.
- **`bpp-mcp` w trybie HTTP** pod publicznym URL-em (patrz niżej).

## Krok 1: uruchom serwer w trybie HTTP

```bash
BPP_BASE_URL=https://bpp.twoja-uczelnia.pl uvx bpp-mcp --http --port 8000
```

Serwer wystawia `/mcp` (Streamable HTTP) oraz
`/.well-known/oauth-protected-resource` (OAuth) — dokładnie to, czego oczekuje
ChatGPT. Szczegóły trybu i bezpieczeństwo: [Uwierzytelnianie](../uwierzytelnianie.md).

### Publiczny URL

ChatGPT musi dosięgnąć serwera po HTTPS. Opcje:

- hosting na maszynie z publicznym adresem i certyfikatem TLS,
- tunel deweloperski: **ngrok**, **Cloudflare Tunnel** lub „Secure MCP Tunnel"
  OpenAI — nada Twojemu lokalnemu portowi publiczny adres `https://…`.

!!! danger "Bezpieczeństwo tunelu"
    Wystawiając serwer publicznie, pamiętaj o mitygacjach z sekcji
    [Uwierzytelnianie](../uwierzytelnianie.md) (read-only serwerowo, scope `read`).
    Nie zmieniaj `--host` bez potrzeby — tunel kieruj na `127.0.0.1:8000`.

## Krok 2: dodaj connector w ChatGPT

1. ChatGPT → zdjęcie profilowe → **Settings**.
2. **Apps & Connectors** (starsza nazwa: **Connectors**) → **Advanced settings** →
   włącz **Developer mode**. (W Business/Enterprise/Edu musi to najpierw
   umożliwić administrator.)
3. W **Apps & Connectors** kliknij **Create** (**+**).
4. Podaj **Name**, **Description** oraz **MCP server URL** = Twój publiczny
   endpoint, np. `https://twoj-host/mcp`.
5. Wybierz uwierzytelnianie: **OAuth** (ChatGPT przeprowadzi logowanie) lub token.
6. **Create** — po powodzeniu ChatGPT wylistuje narzędzia serwera.

!!! note "Nazewnictwo"
    Od 2025-12-17 OpenAI zmienił nazwę „connectors" na „apps" — w UI możesz
    spotkać oba terminy; funkcjonalnie to to samo.

## Zobacz też

- Oficjalnie: [Developer mode and MCP apps in ChatGPT](https://help.openai.com/en/articles/12584461-developer-mode-and-mcp-apps-in-chatgpt),
  [Connect your app to ChatGPT (Apps SDK)](https://developers.openai.com/apps-sdk/deploy/connect-chatgpt),
  [Building MCP servers](https://developers.openai.com/api/docs/mcp).
- [Uwierzytelnianie](../uwierzytelnianie.md) — tryb HTTP/OAuth.
