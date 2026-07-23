"""Serwer FastMCP: lifespan zakłada współdzielony :class:`BppClient`, a każde
z siedmiu narzędzi deleguje do czystej logiki w :mod:`bpp_mcp.tools`.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, replace
from typing import Any

import httpx
from mcp.server.auth.settings import AuthSettings
from mcp.server.fastmcp import Context, FastMCP

from . import oauth_client, token_store, tools
from .auth import WhoamiTokenVerifier, bearer_from_request, set_current_bearer
from .client import BppClient
from .config import BrakKonfiguracji, Config
from .login_state import TokenProvider


@dataclass
class KontekstApp:
    """Zawartość lifespan-context serwera — współdzielony klient HTTP oraz
    (w trybie stdio) provider tokenu OAuth z lokalnego cache."""

    client: BppClient
    bearer_provider: TokenProvider | None = None


async def _client(ctx: Context) -> BppClient:
    """Zwróć współdzielony klient i ustaw token bieżącego żądania.

    Kolejność: token z nagłówka bieżącego requestu (tryb http, K1) wygrywa;
    w stdio, gdy go brak, sięgamy do lokalnego cache przez ``bearer_provider``
    (może odświeżyć token). Brak obu → anonimowo (``None``)."""
    request = getattr(ctx.request_context, "request", None)
    bearer = bearer_from_request(request)
    kctx = ctx.request_context.lifespan_context
    if bearer is None and kctx.bearer_provider is not None:
        bearer = await kctx.bearer_provider.bearer()
    set_current_bearer(bearer)
    return kctx.client


async def szukaj_publikacji(
    ctx: Context,
    q: str,
    rok_od: int | None = None,
    rok_do: int | None = None,
    limit: int = 25,
) -> dict[str, Any]:
    """Rankowane wyszukiwanie pełnotekstowe publikacji w BPP (endpoint
    /szukaj/). Wymaga instancji BPP z Fazą 0 — inaczej zwraca czytelny błąd."""
    return await tools.szukaj_publikacji(await _client(ctx), q, rok_od, rok_do, limit)


async def szukaj_autora(ctx: Context, nazwisko: str) -> dict[str, Any]:
    """Znajdź autorów po (bieżącym) nazwisku — zwraca ID/slug/jednostkę."""
    return await tools.szukaj_autora(await _client(ctx), nazwisko)


async def publikacje_autora(
    ctx: Context,
    id_lub_slug: str,
    rok_od: int | None = None,
    rok_do: int | None = None,
    limit: int = 25,
) -> dict[str, Any]:
    """Publiczne publikacje autora (po ID lub slug). Sufit 100 → flaga obcieto."""
    return await tools.publikacje_autora(
        await _client(ctx), id_lub_slug, rok_od, rok_do, limit
    )


async def publikacje_jednostki(
    ctx: Context,
    id_lub_slug: str,
    rok_od: int | None = None,
    rok_do: int | None = None,
    limit: int = 25,
) -> dict[str, Any]:
    """Publiczne publikacje jednostki i jej pod-jednostek (po ID lub slug)."""
    return await tools.publikacje_jednostki(
        await _client(ctx), id_lub_slug, rok_od, rok_do, limit
    )


async def pobierz_rekord(
    ctx: Context,
    typ: str,
    id: str,
    pelne_dane_autorow: bool = False,
) -> dict[str, Any]:
    """Pobierz rekord (typ: wydawnictwo_ciagle/wydawnictwo_zwarte/patent/
    praca_doktorska/praca_habilitacyjna) z rozwiniętymi hyperlinkami —
    autorami, źródłem, streszczeniami — jako jeden zagnieżdżony obiekt."""
    return await tools.pobierz_rekord(await _client(ctx), typ, id, pelne_dane_autorow)


async def lista_publikacji(
    ctx: Context,
    typ: str,
    rok_od: int | None = None,
    rok_do: int | None = None,
    charakter_formalny: str | None = None,
    zmienione_po: str | None = None,
    limit: int = 25,
    offset: int = 0,
) -> dict[str, Any]:
    """Harvest/przyrost listy publikacji danego typu z filtrami (rok, charakter
    formalny, ostatnio zmienione). Auto-follow paginacji do limitu."""
    return await tools.lista_publikacji(
        await _client(ctx),
        typ,
        rok_od,
        rok_do,
        charakter_formalny,
        zmienione_po,
        limit,
        offset,
    )


async def slownik(ctx: Context, rodzaj: str) -> dict[str, Any]:
    """Pobierz mały słownik referencyjny (charakter_formalny/jezyk/
    dyscyplina_naukowa/…) jednym żądaniem. Odrzuca dane wolumenowe."""
    return await tools.slownik(await _client(ctx), rodzaj)


async def zapytanie_rekord(
    ctx: Context, q: str, limit: int = 25, offset: int = 0
) -> dict[str, Any]:
    """Wykonaj precyzyjne zapytanie DjangoQL po PUBLIKACJACH (bpp.Rekord) —
    autoryzowany endpoint /api/v1/zapytanie/rekord/. Zwraca płaskie rekordy
    w kopercie z laczna_liczba. Pola/operatory/słowniki: najpierw pobierz
    djangoql_schema("rekord"). Wymaga zalogowania (Bearer OAuth albo sesja +
    uprawnienia: superuser lub staff „wprowadzanie danych"). Błędy: 400 zła
    składnia/pole (z pozycją) → popraw q; 401 token; 403 brak uprawnień;
    503 timeout → zawęź."""
    return await tools.zapytanie_rekord(await _client(ctx), q, limit, offset)


async def zapytanie_autor(
    ctx: Context, q: str, limit: int = 25, offset: int = 0
) -> dict[str, Any]:
    """Wykonaj precyzyjne zapytanie DjangoQL po AUTORACH (bpp.Autor) —
    autoryzowany endpoint /api/v1/zapytanie/autor/. Filtruj m.in. po nazwisko,
    imiona, orcid, poprzednie_nazwiska, tytul.skrot, aktualna_jednostka.nazwa,
    pbn_uid.pbnId. Pola PII (email/adnotacje/opis) są zablokowane → 400.
    Auth i błędy jak w zapytanie_rekord."""
    return await tools.zapytanie_autor(await _client(ctx), q, limit, offset)


async def zapytanie_autorzy(
    ctx: Context, q: str, limit: int = 25, offset: int = 0
) -> dict[str, Any]:
    """Wykonaj precyzyjne zapytanie DjangoQL po WPISACH AUTORSTWA (bpp.Autorzy,
    autor-na-rekordzie) — autoryzowany endpoint /api/v1/zapytanie/autorzy/.
    Filtruj m.in. po zapisany_jako, kolejnosc, afiliuje, zatrudniony,
    typ_odpowiedzialnosci.skrot, jednostka.nazwa, dyscyplina_naukowa.nazwa oraz
    trawersacje rekord.… (rekord.rok) i autor.… (autor.nazwisko). Auth i błędy
    jak w zapytanie_rekord."""
    return await tools.zapytanie_autorzy(await _client(ctx), q, limit, offset)


async def djangoql_schema(
    model: str = "rekord", sekcje: list[str] | None = None
) -> dict[str, Any]:
    """Zwróć porcję schematu DjangoQL-dla-LLM danego korzenia (``model``:
    ``rekord`` = bpp.Rekord, ``autor`` = bpp.Autor, ``autorzy`` = bpp.Autorzy —
    po jednym na endpoint /api/v1/zapytanie/*). Służy do KONSTRUKCJI
    precyzyjnych zapytań; wersja schematu jest w nagłówku (``# BPP <wersja>``).

    BEZ parametru ``sekcje`` dostajesz RDZEŃ: reguły języka DjangoQL
    (operatory per typ, negacja, trawersowanie relacji) + pola modelu-korzenia
    z typami + CAŁĄ sekcję ``dictionaries`` z dozwolonymi wartościami
    bezpiecznych słowników zamkniętych (ZERO danych osób/instytucji).

    Pól modeli relacyjnych (bpp.zrodlo, bpp.jednostka, pbn_api.publication…) w
    rdzeniu NIE ma — cały snapshot ma ~74 kB i przebija sufit wyniku narzędzia
    MCP, rdzeń to 20–25% tej objętości. Nazwy sekcji widać w blokach relacji
    modelu-korzenia (zapis ``zrodlo -> bpp.zrodlo``) oraz w polu zwrotu
    ``sekcje_dostepne``. Dobierz je parametrem ``sekcje``, np.
    ``sekcje=["bpp.zrodlo", "bpp.jednostka"]`` — wynik zawiera wtedy WYŁĄCZNIE
    wskazane bloki (bez preambuły i słowników), sklejone w kolejności z pliku.

    Typowy przepływ: jedno wywołanie po rdzeń, a gdy zapytanie trawersuje
    relacje — jedno po komplet potrzebnych sekcji naraz.

    To narzędzie tylko BUDUJE zapytanie. Aby je WYKONAĆ, użyj narzędzi
    zapytanie_rekord / zapytanie_autor / zapytanie_autorzy — wymagają
    zalogowania (Bearer OAuth albo sesja + uprawnienia redaktora); anonimowo
    zwracają 401/403."""
    # Zasób lokalny (dane pakietu) — brak I/O sieciowego, więc nie potrzebuje
    # BppClient z lifespan-contextu.
    return await tools.djangoql_schema(model, sekcje)


# Instrukcja-szablon dla promptu ``zloz_zapytanie_djangoql``. Trzymana jako
# jedna stała modułowa (łatwa do testu jednostkowego, bez odpalania serwera).
# Placeholder ``{opis}`` jest jedynym miejscem interpolacji — dlatego w tekście
# NIE wolno używać nawiasów klamrowych (DjangoQL ich nie potrzebuje, operatory
# to ``= != > ~`` itd.), inaczej ``str.format`` by się wywalił.
PROMPT_ZLOZ_ZAPYTANIE = """\
Jesteś asystentem, który UKŁADA (nie wykonuje) zapytanie w języku DjangoQL dla
systemu BPP. Prośba użytkownika (po polsku):

    {opis}

KROK 1 — POBIERZ SCHEMAT. Najpierw wywołaj narzędzie MCP
`djangoql_schema("rekord")`. Jego wynik jest JEDYNYM źródłem prawdy o polach,
typach, relacjach i dozwolonych wartościach słownikowych. Nie zgaduj nazw pól
ani wartości — bierz je dosłownie ze schematu (sekcja `dictionaries`).

To wywołanie zwraca RDZEŃ: reguły języka, pola modelu-korzenia i pełne
słowniki. Pól modeli relacyjnych w rdzeniu NIE ma — jeśli zapytanie trawersuje
relację (w polach korzenia zapis `zrodlo -> bpp.zrodlo`), dobierz jej pola
DRUGIM wywołaniem z parametrem sekcje, np.
`djangoql_schema("rekord", sekcje=["bpp.zrodlo"])`; podaj wszystkie potrzebne
sekcje naraz, a ich nazwy weź z pola `sekcje_dostepne`.

KROK 2 — REGUŁY KOMPOZYCJI:
- Operator dobierz do TYPU pola:
  - int / date (rok, impact_factor, punktacja, daty): `=` `!=` `>` `>=` `<`
    `<=` oraz `in (…)` dla listy wartości.
  - str tekstowy BEZ słownika (tytuł, uwagi): `~` = "zawiera" (podłańcuch),
    `=` = dokładne dopasowanie całości. Do szukania po fragmencie używaj `~`.
  - bool: `= True` / `= False` (bez cudzysłowów).
  - pole nullable / relacja opcjonalna: test istnienia przez `!= None`
    (albo `= None` dla braku).
- Relacje trawersuj KROPKĄ, schodząc do pola dopasowania podanego w schemacie,
  np. `autorzy.autor.nazwisko ~ "Kowalski"`, `charakter_formalny.nazwa = "…"`,
  `jezyk.nazwa = "angielski"`.
- Wartości słownikowe (charakter_formalny, jezyk, dyscyplina_naukowa, licencje
  OA itd.) wpisuj DOKŁADNIE tak, jak w appendiksie `dictionaries` — co do znaku,
  wielkości liter i polskich znaków. Nie tłumacz i nie skracaj.
- Pola tekstowe bez słownika dopasowuj przez `~` (zawiera).
- Negacja WYŁĄCZNIE operatorem: `!=`, `!~`, `not in (…)`. Nie używaj
  samodzielnego `not …`.
- Łącz warunki przez `and` / `or`; grupuj nawiasami `(` `)` gdy mieszasz
  `and` z `or`, żeby priorytet był jednoznaczny.
- Łańcuchy w cudzysłowach prostych `"…"`; liczby, `True`, `False`, `None` bez
  cudzysłowów.

KROK 3 — ZWALIDUJ zanim oddasz:
- każdy łańcuch w cudzysłowach, liczby/bool/None bez cudzysłowów;
- operator pasuje do typu pola (np. `~` tylko na tekście, `>` tylko na
  liczbie/dacie);
- wartości słownikowe zgadzają się CO DO ZNAKU z sekcją `dictionaries`;
- nawiasy się domykają, priorytet `and`/`or` jest jednoznaczny;
- istnienie/brak relacji wyrażone przez `!= None` / `= None`.

KROK 4 — ODDAJ WYNIK: JEDNO gotowe zapytanie DjangoQL w bloku kodu, a pod nim
jedno zdanie: to zapytanie WYKONASZ narzędziem zapytanie_rekord (model rekord)
po zalogowaniu (Bearer/sesja + uprawnienia redaktora), albo wklejając je do
edytora „zapytanie" w BPP; anonimowe API go nie uruchamia.
"""


def zloz_zapytanie_djangoql(opis: str) -> str:
    """Zwróć instrukcję-wiadomość dla klienta LLM: jak — korzystając z
    narzędzia ``djangoql_schema("rekord")`` — złożyć poprawne zapytanie
    DjangoQL realizujące ``opis`` użytkownika. Prompt tylko KONSTRUUJE
    zapytanie; wykonasz je narzędziem ``zapytanie_rekord`` (po zalogowaniu)."""
    return PROMPT_ZLOZ_ZAPYTANIE.format(opis=opis.strip())


# Wykonywanie zapytań DjangoQL po API jest już dostępne (AUTORYZOWANE) przez
# narzędzia zapytanie_rekord / zapytanie_autor / zapytanie_autorzy wyżej —
# endpointy /api/v1/zapytanie/{rekord,autor,autorzy}/ za Bearer/sesją + gate.
# Anonimowe wykonanie DjangoQL nadal NIE istnieje (i może nigdy nie powstać);
# dlatego te narzędzia poprawnie zwracają 401/403 bez ważnego tokenu/uprawnień.


def _register(mcp: FastMCP) -> None:
    """Zarejestruj 11 narzędzi + prompt na danej instancji FastMCP."""
    mcp.tool()(szukaj_publikacji)
    mcp.tool()(szukaj_autora)
    mcp.tool()(publikacje_autora)
    mcp.tool()(publikacje_jednostki)
    mcp.tool()(pobierz_rekord)
    mcp.tool()(lista_publikacji)
    mcp.tool()(slownik)
    mcp.tool()(zapytanie_rekord)
    mcp.tool()(zapytanie_autor)
    mcp.tool()(zapytanie_autorzy)
    mcp.tool()(djangoql_schema)
    mcp.prompt(
        name="zloz_zapytanie_djangoql",
        description=(
            "Ułóż (nie wykonuj) zapytanie DjangoQL dla modelu bpp.Rekord na "
            "podstawie opisu po polsku — do wklejenia w edytor „zapytanie” BPP."
        ),
    )(zloz_zapytanie_djangoql)


def _auth_kwargs(config: Config) -> dict[str, Any]:
    """Argumenty auth do FastMCP: puste w stdio; w http token_verifier +
    AuthSettings (RS) + host/port."""
    if config.transport != "http":
        return {}
    return {
        "token_verifier": WhoamiTokenVerifier(config.base_url),
        "auth": AuthSettings(
            issuer_url=config.base_url,
            resource_server_url=config.effective_resource_url,
            required_scopes=["read"],
        ),
        "host": config.http_host,
        "port": config.http_port,
    }


def build_mcp(config: Config) -> FastMCP:
    """Zbuduj serwer FastMCP. Lifespan zakłada BppClient związany z TYM config
    (W2 — nie z env), więc verifier i klient używają tej samej instancji BPP."""

    @asynccontextmanager
    async def lifespan(_server: FastMCP) -> AsyncIterator[KontekstApp]:
        client = BppClient(config)
        provider = (
            TokenProvider(config.base_url) if config.transport != "http" else None
        )
        try:
            yield KontekstApp(client=client, bearer_provider=provider)
        finally:
            await client.aclose()

    mcp = FastMCP("bpp-mcp", lifespan=lifespan, **_auth_kwargs(config))
    _register(mcp)
    return mcp


# Modułowy serwer — ZAWSZE stdio (D2: niezależny od env BPP_MCP_TRANSPORT),
# używany przez stdio-entry i istniejące testy importujące ``mcp``.
#
# Bez BPP_BASE_URL nie da się go zbudować, ale import NIE może przez to
# wybuchnąć tracebackiem — ``main()`` ma najpierw wypisać czytelny komunikat
# (a ``--help`` zadziałać w ogóle bez konfiguracji).
try:
    mcp = build_mcp(replace(Config.from_env(), transport="stdio"))
except BrakKonfiguracji:
    mcp = None  # type: ignore[assignment]


def _cmd_login(config: Config) -> None:
    """Przeprowadź logowanie OAuth w przeglądarce i zapisz token do cache."""
    istniejacy = token_store.load(config.base_url)
    try:
        ts = oauth_client.login(
            config.base_url,
            existing_client_id=istniejacy.client_id if istniejacy else None,
        )
    except (httpx.HTTPError, ValueError, TimeoutError, RuntimeError, KeyError) as exc:
        print(f"Logowanie nieudane: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
    token_store.save(ts)
    kto = ts.username or "(nieznany użytkownik)"
    print(f"Zalogowano jako {kto} @ {config.base_url}")


def main() -> None:
    """``bpp-mcp``: bez podkomendy → serwer (stdio; ``--http`` → Streamable HTTP
    + OAuth RS). ``login`` → logowanie w przeglądarce; ``logout`` → wyczyść token."""
    parser = argparse.ArgumentParser(prog="bpp-mcp")
    parser.add_argument(
        "--http", action="store_true", help="Streamable HTTP + OAuth (Resource Server)."
    )
    parser.add_argument("--host", default=None, help="Host HTTP (dom. 127.0.0.1).")
    parser.add_argument("--port", type=int, default=None, help="Port HTTP.")
    sub = parser.add_subparsers(dest="cmd")
    sub.add_parser("login", help="Zaloguj się do BPP (przeglądarka) i zapisz token.")
    sub.add_parser("logout", help="Usuń zapisany token tej instancji BPP.")
    args = parser.parse_args()
    try:
        config = Config.from_env()
    except BrakKonfiguracji as exc:
        print(f"bpp-mcp: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc

    if args.cmd == "login":
        _cmd_login(config)
        return
    if args.cmd == "logout":
        token_store.clear(config.base_url)
        print(f"Wylogowano z {config.base_url}")
        return

    if args.http:
        config = replace(
            config,
            transport="http",
            http_host=args.host or config.http_host,
            http_port=args.port or config.http_port,
        )
    server = build_mcp(config) if config.transport == "http" else mcp
    if config.transport == "http":
        server.run(transport="streamable-http")
    else:
        server.run()


if __name__ == "__main__":
    main()
