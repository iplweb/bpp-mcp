"""Logika siedmiu narzędzi MCP — czyste funkcje async przyjmujące
:class:`~bpp_mcp.client.BppClient` jako pierwszy argument.

Oddzielenie logiki od rejestracji FastMCP (w :mod:`bpp_mcp.server`) pozwala
testować narzędzia bezpośrednio pod respx, bez stawiania serwera.
"""

from __future__ import annotations

import asyncio
from importlib import resources
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


# Zbundlowane schematy DjangoQL-dla-LLM (dane pakietu w ``bpp_mcp/data/``).
# Mapa ``model → nazwa pliku``. Na razie tylko ``rekord`` (bpp.Rekord); klucz
# jest tu, by dołożenie kolejnych modeli było jedną linią. Źródło pliku:
# repo iplweb/bpp-schema-for-llm (generowane z instancji BPP, przeskanowane —
# wartości wyłącznie bezpiecznych słowników, ZERO danych osób/instytucji).
_SCHEMATY_DJANGOQL: dict[str, str] = {
    "rekord": "rekord_djangoql_schema.compact.txt",
}


# Krótka wskazówka doklejana do zwrotu ``djangoql_schema`` — przypomina LLM-owi,
# że schemat służy do ZŁOŻENIA zapytania (do wklejenia), a nie do wykonania.
_JAK_ZLOZYC = (
    "Użyj tych pól i sekcji `dictionaries` jako jedynego źródła prawdy: "
    "operator dobierz do typu pola (int/date: = != > >= < <= in; tekst bez "
    "słownika: ~ zawiera / = dokładnie; bool: = True/False; nullable: != None), "
    "relacje trawersuj kropką, wartości słownikowe wpisuj dosłownie. Złóż JEDNO "
    "zapytanie DjangoQL; wykonasz je narzędziem zapytanie_rekord (model rekord) "
    "po zalogowaniu (Bearer/sesja + uprawnienia redaktora) — anon-API go nie "
    "uruchamia."
)


def _wczytaj_schemat_djangoql(model: str) -> str:
    """Wczytaj zbundlowany plik schematu przez ``importlib.resources`` (nie
    ścieżki względne — działa też z zainstalowanego wheela / zip-a)."""
    nazwa_pliku = _SCHEMATY_DJANGOQL[model]
    # Kotwiczymy na pakiecie ``bpp_mcp`` i schodzimy do ``data/`` — nie wymaga,
    # by ``data`` był osobnym (sub)pakietem z ``__init__.py``.
    return (
        resources.files("bpp_mcp")
        .joinpath("data", nazwa_pliku)
        .read_text(encoding="utf-8")
    )


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
        wyniki, laczna, niepelne = await client.get_paginated("szukaj/", params, limit)
    except BppNotFound as exc:
        raise BppError(_KOMUNIKAT_BRAK_SZUKAJ) from exc
    wyniki = [_dopisz_typ_i_pk(dict(w)) for w in wyniki]
    return {
        "laczna_liczba": laczna,
        "zwrocono": len(wyniki),
        "niepelne": niepelne,
        "wyniki": wyniki,
    }


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
        autorzy, laczna, niepelne = await client.get_paginated(
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
        "niepelne": niepelne,
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
    # ``count`` z endpointu recent_* to len(wynik) PO obcięciu (nie łączna liczba
    # prac encji) — mylące dla LLM-a. Wycinamy je i eksponujemy jako ``zwrocono``
    # (liczba faktycznie zwróconych), spójnie z innymi narzędziami. Łączny total
    # NIE jest dostępny z tego endpointu API — stąd tylko ``zwrocono`` + ``obcieto``.
    wynik = {k: v for k, v in dane.items() if k not in ("publications", "count")}
    wynik["zwrocono"] = len(publikacje)
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
    # ``str.isdigit()`` przepuszcza cyfry unicode (np. "٣".isdigit() == True), które
    # trafiłyby do URL-a jako nie-ASCII — wymuszamy więc czyste ASCII 0-9.
    id_str = str(id)
    if not (id_str.isascii() and id_str.isdigit()):
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
    wyniki, laczna, niepelne = await client.get_paginated(f"{typ}/", params, limit)
    return {
        "laczna_liczba": laczna,
        "zwrocono": len(wyniki),
        "niepelne": niepelne,
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


#: Sufit ``limit`` dla zapytań DjangoQL. Endpoint API twardo capuje pojedyncze
#: żądanie do 100; paginacja i tak stronicuje porcjami ≤ ``PAGE_LIMIT``.
MAKS_LIMIT_ZAPYTANIE = 100


def _blad_zapytania(exc: BppError, *, stdio: bool = False) -> BppError:
    """Zmapuj kod stanu odpowiedzi endpointu ``zapytanie/*`` na czytelny,
    „naprawialny" komunikat dla agenta. Zwraca NOWY :class:`BppError` dla
    znanych statusów (400/401/403/503); dla nieznanych zwraca ``exc`` bez zmian.
    W trybie stdio 401 podpowiada jednorazowe ``bpp-mcp login`` (hybryda).
    """
    status = exc.status_code
    if status == 400:
        info = exc.payload if isinstance(exc.payload, dict) else {}
        opis = info.get("error") or "niepoprawne zapytanie DjangoQL"
        line, column = info.get("line"), info.get("column")
        gdzie = f" (linia {line}, kolumna {column})" if line and column else ""
        return BppError(
            f"Zapytanie DjangoQL odrzucone{gdzie}: {opis}. Popraw zapytanie "
            "(nazwa pola/składnia; pola PII jak autor.email są zablokowane) i ponów.",
            status_code=400,
            payload=exc.payload,
        )
    if status == 401:
        if stdio:
            return BppError(
                "Nie jesteś zalogowany lub token wygasł (401). Zaloguj się raz: "
                "uruchom `bpp-mcp login` w terminalu, a potem ponów zapytanie.",
                status_code=401,
            )
        return BppError(
            "Nieprawidłowy lub wygasły token (401) — wymagane ponowne "
            "uwierzytelnienie OAuth (endpoint /o/ instancji BPP).",
            status_code=401,
        )
    if status == 403:
        return BppError(
            "Brak uprawnień do zapytań DjangoQL (403) — wymagany superuser albo "
            "staff w grupie „wprowadzanie danych”.",
            status_code=403,
        )
    if status == 503:
        return BppError(
            "Zapytanie trwało za długo (503, statement_timeout 8 s) — zawęź "
            "warunki (mniejszy zakres lat, bardziej selektywne pola).",
            status_code=503,
        )
    return exc


async def _zapytanie(
    client: BppClient, endpoint: str, q: str, limit: int, offset: int
) -> dict[str, Any]:
    """Wspólny trzon trzech narzędzi DjangoQL. Puste ``q`` → pusty wynik bez
    żądania (endpoint i tak zwróciłby ``[]``). Kody 400/401/403/503 mapowane na
    czytelne błędy. 5xx bez ponawiania (503 = deterministyczny timeout)."""
    q = (q or "").strip()
    if not q:
        return {"laczna_liczba": 0, "zwrocono": 0, "niepelne": False, "wyniki": []}
    limit = _clamp_limit(limit, MAKS_LIMIT_ZAPYTANIE)
    params: dict[str, Any] = {"q": q}
    if offset:
        params["offset"] = offset
    try:
        wyniki, laczna, niepelne = await client.get_paginated(
            endpoint, params, limit, retry_5xx=False
        )
    except BppError as exc:
        if exc.status_code in (400, 401, 403, 503):
            raise _blad_zapytania(exc, stdio=client.transport == "stdio") from exc
        raise
    return {
        "laczna_liczba": laczna,
        "zwrocono": len(wyniki),
        "niepelne": niepelne,
        "wyniki": wyniki,
    }


async def zapytanie_rekord(
    client: BppClient, q: str, limit: int = 25, offset: int = 0
) -> dict[str, Any]:
    """Precyzyjne zapytanie DjangoQL po publikacjach (``bpp.Rekord``) —
    autoryzowany endpoint ``/api/v1/zapytanie/rekord/``.

    Wymaga Bearer/sesji + uprawnień (superuser lub staff „wprowadzanie danych").
    Pola/typy/operatory/słowniki: użyj narzędzia ``djangoql_schema("rekord")``.
    Zwraca płaskie pozycje (jak ``/szukaj/``) w kopercie z ``laczna_liczba``.
    """
    return await _zapytanie(client, "zapytanie/rekord/", q, limit, offset)


async def zapytanie_autor(
    client: BppClient, q: str, limit: int = 25, offset: int = 0
) -> dict[str, Any]:
    """Precyzyjne zapytanie DjangoQL po autorach (``bpp.Autor``) — autoryzowany
    endpoint ``/api/v1/zapytanie/autor/``.

    Pola do filtrowania m.in.: ``nazwisko``, ``imiona``, ``orcid``,
    ``poprzednie_nazwiska``, ``system_kadrowy_id``, ``tytul.skrot``,
    ``aktualna_jednostka.nazwa``, ``pbn_uid.pbnId`` (trawersacja do PBN).
    Pola PII (``email``/``adnotacje``/``opis``) są zablokowane → 400.
    """
    return await _zapytanie(client, "zapytanie/autor/", q, limit, offset)


async def zapytanie_autorzy(
    client: BppClient, q: str, limit: int = 25, offset: int = 0
) -> dict[str, Any]:
    """Precyzyjne zapytanie DjangoQL po wpisach autorstwa (``bpp.Autorzy``) —
    autoryzowany endpoint ``/api/v1/zapytanie/autorzy/``.

    Pola m.in.: ``zapisany_jako``, ``kolejnosc``, ``afiliuje``, ``zatrudniony``,
    ``typ_odpowiedzialnosci.skrot``, ``jednostka.nazwa``,
    ``dyscyplina_naukowa.nazwa`` oraz trawersacje ``rekord.…`` (``rekord.rok``,
    ``rekord.charakter_formalny.nazwa``) i ``autor.…`` (``autor.nazwisko``).
    """
    return await _zapytanie(client, "zapytanie/autorzy/", q, limit, offset)


async def djangoql_schema(model: str = "rekord") -> dict[str, Any]:
    """Zwróć zbundlowany schemat DjangoQL-dla-LLM danego modelu (na razie
    tylko ``rekord`` = ``bpp.Rekord``).

    Zawartość zwracanego tekstu:

    * reguły języka DjangoQL (operatory per typ, negacja, trawersowanie
      relacji, sufiksy ``__year``/``__count`` itd.) — z nagłówka pliku,
    * listę pól modelu Rekord z typami i (dla relacji) polem dopasowania,
    * sekcję ``dictionaries`` — dozwolone WARTOŚCI wyłącznie dla bezpiecznych
      słowników zamkniętych (charaktery, dyscypliny, języki, licencje OA…);
      ZERO danych osób/instytucji.

    Po co: pozwala zbudować PRECYZYJNE zapytanie DjangoQL (np.
    ``rok >= 2020 and jezyk.nazwa = "angielski" and impact_factor > 0``)
    zamiast zgadywać nazwy pól i dozwolone wartości.

    To narzędzie służy do KONSTRUKCJI zapytań. Aby zapytanie WYKONAĆ, użyj
    ``zapytanie_rekord`` / ``zapytanie_autor`` / ``zapytanie_autorzy`` —
    autoryzowane endpointy ``/api/v1/zapytanie/*`` (Bearer/sesja + uprawnienia
    redaktora; anonimowo 401/403). Wersja schematu jest w pierwszej linii
    nagłówka (``# BPP <wersja>``) — musi pasować do wersji odpytywanej instancji.
    """
    if model not in _SCHEMATY_DJANGOQL:
        dostepne = ", ".join(_SCHEMATY_DJANGOQL)
        raise BppError(f"Nieznany model schematu '{model}'. Dostępne: {dostepne}.")
    tekst = _wczytaj_schemat_djangoql(model)
    return {"model": model, "schemat": tekst, "jak_zlozyc": _JAK_ZLOZYC}
