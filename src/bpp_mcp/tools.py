"""Logika siedmiu narzędzi MCP — czyste funkcje async przyjmujące
:class:`~bpp_mcp.client.BppClient` jako pierwszy argument.

Oddzielenie logiki od rejestracji FastMCP (w :mod:`bpp_mcp.server`) pozwala
testować narzędzia bezpośrednio pod respx, bez stawiania serwera.
"""

from __future__ import annotations

import asyncio
from typing import Any

from .catalog import (
    CATALOG,
    SLOWNIKI,
    SLOWNIKI_WOLUMENOWE,
    TYPY_REKORDOW,
    rozbij_rekord_url,
    rozbij_tuple_id,
)
from .client import BppClient, BppError, BppNotFound

# Twardy górny sufit ``limit`` dla narzędzi listujących/wyszukujących. BPP nie
# deklaruje ``max_limit`` po stronie DRF, więc bez tego clampa ``limit=1_000_000``
# poszłoby wprost do paginacji i mogłoby zdmuchnąć instancję. Paginacja i tak
# stronicuje porcjami (``PAGE_LIMIT``), ten sufit ogranicza łączną liczbę pozycji.
MAKS_LIMIT = 200
MAKS_LIMIT_RECENT = 100


def _clamp_limit(limit: int, sufit: int = MAKS_LIMIT) -> int:
    """Przytnij ``limit`` do przedziału ``[1, sufit]`` (obrona przed skrajnymi
    wartościami wysadzającymi instancję / przed ``limit <= 0``)."""
    return max(1, min(limit, sufit))


_KOMUNIKAT_BRAK_SZUKAJ = (
    "Ta instancja BPP nie udostępnia endpointu /szukaj/ — wymaga wersji "
    "BPP z Fazą 0 (rozszerzenie API o wyszukiwanie). Użyj publikacje_autora / "
    "publikacje_jednostki albo lista_publikacji, które działają na każdej "
    "wersji API."
)


def _zakres_roku(rok_od: int | None, rok_do: int | None) -> dict[str, int]:
    params: dict[str, int] = {}
    if rok_od is not None:
        params["rok_od"] = rok_od
    if rok_do is not None:
        params["rok_do"] = rok_do
    return params


def _dopisz_typ_i_pk(pozycja: dict[str, Any]) -> dict[str, Any]:
    """Do pozycji ``/szukaj/`` dopisz rozłożony ``typ`` + ``pk`` (dla
    późniejszego :func:`pobierz_rekord`), na bazie ``rekord_url``."""
    typ, pk = rozbij_rekord_url(pozycja.get("rekord_url"))
    if typ is not None:
        pozycja["typ"] = typ
        pozycja["pk"] = pk
    return pozycja


def _znormalizuj_pozycje_recent(pozycja: dict[str, Any]) -> dict[str, Any]:
    """Rozłóż ``id`` w formacie ``"(6, 123)"`` na ``content_type_id`` + ``pk``."""
    ct, pk = rozbij_tuple_id(pozycja.get("id"))
    if ct is not None:
        pozycja["content_type_id"] = ct
        pozycja["pk"] = pk
    return pozycja


async def szukaj_publikacji(
    client: BppClient,
    q: str,
    rok_od: int | None = None,
    rok_do: int | None = None,
    limit: int = 25,
) -> dict[str, Any]:
    """Rankowane wyszukiwanie pełnotekstowe publikacji (endpoint ``/szukaj/``).

    Miękka degradacja: gdy instancja BPP nie ma jeszcze Fazy 0, endpoint
    zwraca 404 → podnosimy czytelny :class:`BppError` (nie traceback).
    """
    limit = _clamp_limit(limit)
    params = {"q": q, **_zakres_roku(rok_od, rok_do)}
    try:
        wyniki, laczna = await client.get_paginated("szukaj/", params, limit)
    except BppNotFound as exc:
        raise BppError(_KOMUNIKAT_BRAK_SZUKAJ) from exc
    wyniki = [_dopisz_typ_i_pk(dict(w)) for w in wyniki]
    return {"laczna_liczba": laczna, "zwrocono": len(wyniki), "wyniki": wyniki}


async def szukaj_autora(client: BppClient, nazwisko: str) -> dict[str, Any]:
    """Wyszukiwanie autorów po nazwisku (``autor?nazwisko=`` z Fazy 0).

    UWAGA — wykrywanie możliwości: django-filter **po cichu ignoruje** nieznane
    parametry. Na starej instancji BPP (bez Fazy 0) filtr ``nazwisko`` zostanie
    zignorowany, a endpoint zwróci WSZYSTKICH autorów bez błędu. Zwracamy więc
    flagę ``mozliwe_ze_niefiltrowane`` gdy trafień jest podejrzanie dużo — to
    sygnał, że instancja może nie wspierać filtra. Filtr obejmuje wyłącznie
    bieżące ``nazwisko`` (świadomie NIE ``poprzednie_nazwiska`` w v1).
    """
    try:
        autorzy, laczna = await client.get_paginated(
            "autor/", {"nazwisko": nazwisko}, limit=MAKS_LIMIT_RECENT
        )
    except BppNotFound as exc:
        raise BppError(
            "Endpoint autora niedostępny na tej instancji BPP: " + str(exc)
        ) from exc
    podejrzanie_duzo = len(autorzy) >= MAKS_LIMIT_RECENT
    return {
        "laczna_liczba": laczna,
        "zwrocono": len(autorzy),
        "mozliwe_ze_niefiltrowane": podejrzanie_duzo,
        "autorzy": autorzy,
    }


async def _publikacje_encji(
    client: BppClient,
    endpoint: str,
    id_lub_slug: str,
    rok_od: int | None,
    rok_do: int | None,
    limit: int,
    czytelny_404: str,
) -> dict[str, Any]:
    limit = _clamp_limit(limit, MAKS_LIMIT_RECENT)
    params = {"limit": limit, **_zakres_roku(rok_od, rok_do)}
    try:
        dane = await client.get_json(
            f"{endpoint}/{id_lub_slug}/", params=params, use_cache=False
        )
    except BppNotFound as exc:
        raise BppError(czytelny_404) from exc
    publikacje = [
        _znormalizuj_pozycje_recent(dict(p)) for p in dane.get("publications", [])
    ]
    # recent_* ma twardy sufit 100 i brak offsetu — dobicie do żądanego ``limit``
    # (nie tylko do 100) sygnalizuje, że mogą istnieć dalsze, nieujawnione pozycje.
    obcieto = len(publikacje) >= limit
    wynik = {k: v for k, v in dane.items() if k != "publications"}
    wynik["obcieto"] = obcieto
    wynik["publikacje"] = publikacje
    return wynik


async def publikacje_autora(
    client: BppClient,
    id_lub_slug: str,
    rok_od: int | None = None,
    rok_do: int | None = None,
    limit: int = 25,
) -> dict[str, Any]:
    """Publiczne publikacje autora (endpoint ``recent_author_publications``).

    Identyfikator: numeryczne ID albo slug. Sufit 100 pozycji — przy dobiciu
    do limitu zwracamy ``obcieto: true`` (pełny harvest per autor wymaga
    filtra ``?autor=`` na tabelach through albo chunkowania po latach).
    """
    return await _publikacje_encji(
        client,
        "recent_author_publications",
        id_lub_slug,
        rok_od,
        rok_do,
        limit,
        "Autor niewidoczny lub nie istnieje (pokazuj=False albo zły identyfikator).",
    )


async def publikacje_jednostki(
    client: BppClient,
    id_lub_slug: str,
    rok_od: int | None = None,
    rok_do: int | None = None,
    limit: int = 25,
) -> dict[str, Any]:
    """Publiczne publikacje jednostki wraz z pod-jednostkami (endpoint
    ``recent_unit_publications``). Identyfikator: ID albo slug. Sufit 100
    pozycji → ``obcieto: true`` przy dobiciu do limitu."""
    return await _publikacje_encji(
        client,
        "recent_unit_publications",
        id_lub_slug,
        rok_od,
        rok_do,
        limit,
        "Jednostka niewidoczna lub nie istnieje (widoczna=False albo zły id).",
    )


async def _rozwin_autora_through(
    client: BppClient, url: str, pelne_dane_autorow: bool
) -> dict[str, Any]:
    """Pobierz JEDEN rekord through (autor-w-publikacji) i zbuduj płaski wpis.

    Domyślnie 1 hop: bierzemy ``zapisany_jako`` (nazwisko jak wydrukowane) oraz
    ``autor_url`` — BEZ drugiego hopu do ``autor-detail``. Dopiero
    ``pelne_dane_autorow=True`` dociąga pełny profil autora pod kluczem
    ``autor``.
    """
    through = await client.get_json(url)
    wpis: dict[str, Any] = {
        "zapisany_jako": through.get("zapisany_jako"),
        "typ_odpowiedzialnosci": through.get("typ_odpowiedzialnosci"),
        "kolejnosc": through.get("kolejnosc"),
        "afiliuje": through.get("afiliuje"),
        "procent": through.get("procent"),
        "autor_url": through.get("autor"),
        "jednostka_url": through.get("jednostka"),
        "dyscyplina_naukowa_url": through.get("dyscyplina_naukowa"),
    }
    if pelne_dane_autorow and through.get("autor"):
        wpis["autor"] = await client.get_json(through["autor"])
    return wpis


async def pobierz_rekord(
    client: BppClient,
    typ: str,
    id: str,
    pelne_dane_autorow: bool = False,
) -> dict[str, Any]:
    """Pobierz detal publikacji i rozwiń hyperlinki w JEDEN zagnieżdżony obiekt.

    Rozwijanie sterowane :data:`bpp_mcp.catalog.CATALOG` (per-typ). Autorzy:
    domyślnie ``zapisany_jako`` + ``autor_url`` (1 hop na rekord through),
    ``pelne_dane_autorow=True`` dociąga profile. Rozwijanie równoległe
    (semafor + cache po stronie klienta).
    """
    spec = CATALOG.get(typ)
    if spec is None:
        raise BppError(
            f"Nieznany typ rekordu '{typ}'. Dozwolone: {', '.join(TYPY_REKORDOW)}."
        )
    # Waliduj id ZANIM trafi do interpolacji ścieżki — inaczej np. id="../autor/5"
    # skleiłoby nieoczekiwany URL (path traversal poza zamierzony endpoint).
    if not str(id).isdigit():
        raise BppError(
            f"Nieprawidłowy identyfikator '{id}' — oczekiwano liczby całkowitej "
            "(PK rekordu)."
        )
    try:
        detal = await client.get_json(f"{spec.endpoint}/{id}/", use_cache=False)
    except BppNotFound as exc:
        raise BppError(
            f"Rekord {typ}/{id} nie istnieje lub jest ukryty w API."
        ) from exc

    wynik: dict[str, Any] = dict(detal)
    wynik["typ"] = typ

    if spec.autorzy:
        through_urls = detal.get(spec.autorzy) or []
        autorzy = await asyncio.gather(
            *(
                _rozwin_autora_through(client, u, pelne_dane_autorow)
                for u in through_urls
            )
        )
        wynik[spec.autorzy] = sorted(
            autorzy, key=lambda a: (a.get("kolejnosc") is None, a.get("kolejnosc"))
        )

    for pole in spec.relacje_pojedyncze:
        url = detal.get(pole)
        if url:
            wynik[pole] = await client.get_json(url)

    for pole in spec.relacje_wielokrotne:
        urls = detal.get(pole) or []
        wynik[pole] = list(await asyncio.gather(*(client.get_json(u) for u in urls)))

    return wynik


async def lista_publikacji(
    client: BppClient,
    typ: str,
    rok_od: int | None = None,
    rok_do: int | None = None,
    charakter_formalny: str | None = None,
    zmienione_po: str | None = None,
    limit: int = 25,
    offset: int = 0,
) -> dict[str, Any]:
    """Harvest / przyrostowe pobieranie listy publikacji danego typu.

    Filtry mapowane na konwencje API: ``rok_od→rok_min``, ``rok_do→rok_max``,
    ``zmienione_po→ostatnio_zmieniony_after``. ``charakter_formalny`` i pełny
    zakres roku są wspierane dla ``wydawnictwo_ciagle`` / ``wydawnictwo_zwarte``;
    patenty i prace dr/hab filtrują węziej (``rok`` / ``ostatnio_zmieniony``).
    """
    spec = CATALOG.get(typ)
    if spec is None:
        raise BppError(f"Nieznany typ '{typ}'. Dozwolone: {', '.join(TYPY_REKORDOW)}.")
    # django-filter CICHO ignoruje nieobsługiwane parametry, więc doklejenie
    # charakter_formalny do typu, który go nie filtruje (patent / praca dr/hab),
    # dałoby fałszywie „przefiltrowany" wynik. Odrzucamy jawnie zamiast milczeć.
    chf_niewspierany = (
        charakter_formalny is not None
        and "charakter_formalny" not in spec.filtry_dodatkowe
    )
    if chf_niewspierany:
        raise BppError(
            f"Typ '{typ}' nie wspiera filtra 'charakter_formalny' "
            "(obsługują go tylko wydawnictwo_ciagle i wydawnictwo_zwarte). "
            "Usuń ten filtr albo wybierz jeden z tych dwóch typów."
        )
    limit = _clamp_limit(limit)
    params: dict[str, Any] = {}
    if rok_od is not None:
        params["rok_min"] = rok_od
    if rok_do is not None:
        params["rok_max"] = rok_do
    if charakter_formalny is not None:
        params["charakter_formalny"] = charakter_formalny
    if zmienione_po is not None:
        params["ostatnio_zmieniony_after"] = zmienione_po
    if offset:
        params["offset"] = offset
    wyniki, laczna = await client.get_paginated(f"{typ}/", params, limit)
    return {
        "laczna_liczba": laczna,
        "zwrocono": len(wyniki),
        "typ": typ,
        "wyniki": wyniki,
    }


async def slownik(client: BppClient, rodzaj: str) -> dict[str, Any]:
    """Pobierz małą tabelę referencyjną (tłumaczenie ID↔nazwa) jednym żądaniem.

    Biała lista :data:`bpp_mcp.catalog.SLOWNIKI`. Rodzaje wolumenowe
    (konferencja/wydawca/nagroda/…) są odrzucane z czytelnym błędem — to nie
    słowniki, tylko duże dane, po które chodzi się przez wyszukiwanie/listy.
    """
    if rodzaj in SLOWNIKI_WOLUMENOWE:
        raise BppError(
            f"'{rodzaj}' to dane wolumenowe, nie mały słownik — poza zakresem "
            "slownik(). Użyj wyszukiwania lub dedykowanego narzędzia."
        )
    if rodzaj not in SLOWNIKI:
        raise BppError(f"Nieznany słownik '{rodzaj}'. Dostępne: {', '.join(SLOWNIKI)}.")
    dane = await client.get_json(f"{rodzaj}/", params={"limit": 500})
    pozycje = dane.get("results", dane) if isinstance(dane, dict) else dane
    return {"rodzaj": rodzaj, "count": len(pozycje), "pozycje": pozycje}
