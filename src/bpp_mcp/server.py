"""Serwer FastMCP: lifespan zakłada współdzielony :class:`BppClient`, a każde
z siedmiu narzędzi deleguje do czystej logiki w :mod:`bpp_mcp.tools`.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any

from mcp.server.fastmcp import Context, FastMCP

from . import tools
from .client import BppClient
from .config import Config


@dataclass
class KontekstApp:
    """Zawartość lifespan-context serwera — współdzielony klient HTTP."""

    client: BppClient


@asynccontextmanager
async def lifespan(_server: FastMCP) -> AsyncIterator[KontekstApp]:
    client = BppClient(Config.from_env())
    try:
        yield KontekstApp(client=client)
    finally:
        await client.aclose()


mcp = FastMCP("bpp-mcp", lifespan=lifespan)


def _client(ctx: Context) -> BppClient:
    return ctx.request_context.lifespan_context.client


@mcp.tool()
async def szukaj_publikacji(
    ctx: Context,
    q: str,
    rok_od: int | None = None,
    rok_do: int | None = None,
    limit: int = 25,
) -> dict[str, Any]:
    """Rankowane wyszukiwanie pełnotekstowe publikacji w BPP (endpoint
    /szukaj/). Wymaga instancji BPP z Fazą 0 — inaczej zwraca czytelny błąd."""
    return await tools.szukaj_publikacji(_client(ctx), q, rok_od, rok_do, limit)


@mcp.tool()
async def szukaj_autora(ctx: Context, nazwisko: str) -> dict[str, Any]:
    """Znajdź autorów po (bieżącym) nazwisku — zwraca ID/slug/jednostkę."""
    return await tools.szukaj_autora(_client(ctx), nazwisko)


@mcp.tool()
async def publikacje_autora(
    ctx: Context,
    id_lub_slug: str,
    rok_od: int | None = None,
    rok_do: int | None = None,
    limit: int = 25,
) -> dict[str, Any]:
    """Publiczne publikacje autora (po ID lub slug). Sufit 100 → flaga obcieto."""
    return await tools.publikacje_autora(
        _client(ctx), id_lub_slug, rok_od, rok_do, limit
    )


@mcp.tool()
async def publikacje_jednostki(
    ctx: Context,
    id_lub_slug: str,
    rok_od: int | None = None,
    rok_do: int | None = None,
    limit: int = 25,
) -> dict[str, Any]:
    """Publiczne publikacje jednostki i jej pod-jednostek (po ID lub slug)."""
    return await tools.publikacje_jednostki(
        _client(ctx), id_lub_slug, rok_od, rok_do, limit
    )


@mcp.tool()
async def pobierz_rekord(
    ctx: Context,
    typ: str,
    id: str,
    pelne_dane_autorow: bool = False,
) -> dict[str, Any]:
    """Pobierz rekord (typ: wydawnictwo_ciagle/wydawnictwo_zwarte/patent/
    praca_doktorska/praca_habilitacyjna) z rozwiniętymi hyperlinkami —
    autorami, źródłem, streszczeniami — jako jeden zagnieżdżony obiekt."""
    return await tools.pobierz_rekord(_client(ctx), typ, id, pelne_dane_autorow)


@mcp.tool()
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
        _client(ctx),
        typ,
        rok_od,
        rok_do,
        charakter_formalny,
        zmienione_po,
        limit,
        offset,
    )


@mcp.tool()
async def slownik(ctx: Context, rodzaj: str) -> dict[str, Any]:
    """Pobierz mały słownik referencyjny (charakter_formalny/jezyk/
    dyscyplina_naukowa/…) jednym żądaniem. Odrzuca dane wolumenowe."""
    return await tools.slownik(_client(ctx), rodzaj)


@mcp.tool()
async def djangoql_schema(model: str = "rekord") -> dict[str, Any]:
    """Zwróć zbundlowany schemat DjangoQL-dla-LLM modelu bpp.Rekord: reguły
    języka DjangoQL + pola/typy/operatory/relacje + dozwolone WARTOŚCI wyłącznie
    bezpiecznych słowników (ZERO danych osób/instytucji). Służy do KONSTRUKCJI
    precyzyjnych zapytań — wersja schematu jest w nagłówku (``# BPP <wersja>``).

    UWAGA: samo WYKONANIE zapytania DjangoQL („zapytanie") w BPP wymaga
    ZALOGOWANEGO użytkownika i nie ma go jeszcze w publicznym anon-API — to
    narzędzie tylko buduje zapytania, nie uruchamia ich."""
    # Zasób lokalny (dane pakietu) — brak I/O sieciowego, więc nie potrzebuje
    # BppClient z lifespan-contextu.
    return await tools.djangoql_schema(model)


# TODO(anon-API): gdy publiczne API BPP zyska wykonywanie zapytań DjangoQL dla
# użytkownika anonimowego, dołożyć tu narzędzie ``zapytanie(query: str)``
# delegujące do np. ``tools.zapytanie`` (POST/GET do endpointu wyszukiwania).
# Konfiguracja endpointu → catalog.py / config.py. Dziś funkcja „zapytanie"
# jest tylko dla zalogowanych, więc świadomie NIE rejestrujemy tego narzędzia.


def main() -> None:
    """Punkt wejścia konsoli (``bpp-mcp``) — uruchamia serwer po stdio."""
    mcp.run()


if __name__ == "__main__":
    main()
