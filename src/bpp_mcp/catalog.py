"""Kuratorowana wiedza o kształcie API BPP dzielona przez narzędzia MCP.

Zawiera:

* :data:`CATALOG` — mapa ``typ → {endpoint, relacje do rozwinięcia}`` dla
  pięciu typów rekordów obecnych w :class:`Rekord` (ciągłe, zwarte, patent,
  praca doktorska, praca habilitacyjna). Steruje głębokością rozwijania
  hyperlinków w :func:`bpp_mcp.tools.pobierz_rekord`,
* :data:`SLOWNIKI` — biała lista MAŁYCH tabel referencyjnych dostępnych przez
  :func:`bpp_mcp.tools.slownik`,
* :data:`SLOWNIKI_WOLUMENOWE` — jawnie odrzucane „słowniki" o dużej liczności
  (konferencja/wydawca/nagroda), które nie należą do :func:`slownik`,
* helpery normalizacji identyfikatorów rekordów.

Świadomie utrzymywane ręcznie (bez generatora z YAML — YAGNI). Weryfikowane
z serializerami ``src/api_v1/serializers/`` instancji BPP.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TypRekordu:
    """Opis jednego typu publikacji i jego relacji do rozwinięcia."""

    endpoint: str
    # Pole listy przez-autorskiej (through) z płaskim ``zapisany_jako``.
    # ``None`` gdy typ nie ma tabeli through (prace dr/hab mają pojedynczy
    # ``autor`` jako bezpośredni URL — patrz ``relacje_pojedyncze``).
    autorzy: str | None = None
    # Relacje 1:1 — pojedynczy URL do rozwinięcia w obiekt.
    relacje_pojedyncze: tuple[str, ...] = ()
    # Relacje 1:N — lista URL-i do rozwinięcia w listę obiektów.
    relacje_wielokrotne: tuple[str, ...] = ()
    # Białe listy filtrów opcjonalnych (poza uniwersalnym zakresem roku
    # i ``zmienione_po``) faktycznie honorowanych przez django-filter danego
    # endpointu. django-filter CICHO ignoruje nieznane parametry, więc
    # doklejenie np. ``charakter_formalny`` do typu, który go nie filtruje,
    # dałoby fałszywie „przefiltrowany" wynik. Sterują walidacją w
    # :func:`bpp_mcp.tools.lista_publikacji`.
    filtry_dodatkowe: frozenset[str] = frozenset()


CATALOG: dict[str, TypRekordu] = {
    # Wydawnictwo ciągłe: autorzy (through), źródło, streszczenia, zewn. bazy.
    "wydawnictwo_ciagle": TypRekordu(
        endpoint="wydawnictwo_ciagle",
        autorzy="autorzy_set",
        relacje_pojedyncze=("zrodlo",),
        relacje_wielokrotne=("streszczenia", "zewnetrzna_baza_danych"),
        filtry_dodatkowe=frozenset({"charakter_formalny"}),
    ),
    # Wydawnictwo zwarte: NIE ma zrodlo ani zewnetrzna_baza_danych; ma serię.
    # ``wydawnictwo_nadrzedne`` świadomie NIE rozwijane (ryzyko rekurencji) —
    # pozostaje jako goły URL w wyniku.
    "wydawnictwo_zwarte": TypRekordu(
        endpoint="wydawnictwo_zwarte",
        autorzy="autorzy_set",
        relacje_pojedyncze=("seria_wydawnicza",),
        relacje_wielokrotne=("streszczenia",),
        filtry_dodatkowe=frozenset({"charakter_formalny"}),
    ),
    # Patent: tylko autorzy (through). rodzaj_prawa/zasieg są inline (string).
    "patent": TypRekordu(
        endpoint="patent",
        autorzy="autorzy_set",
    ),
    # Prace dr/hab: pojedynczy bezpośredni autor (+ promotor/jednostka/wydawca),
    # bez tabeli through.
    "praca_doktorska": TypRekordu(
        endpoint="praca_doktorska",
        autorzy=None,
        relacje_pojedyncze=("autor", "promotor", "jednostka", "wydawca"),
    ),
    "praca_habilitacyjna": TypRekordu(
        endpoint="praca_habilitacyjna",
        autorzy=None,
        relacje_pojedyncze=("autor", "jednostka", "wydawca"),
    ),
}

TYPY_REKORDOW: tuple[str, ...] = tuple(CATALOG.keys())


# Biała lista małych tabel referencyjnych (jedno żądanie ?limit=500).
SLOWNIKI: tuple[str, ...] = (
    "charakter_formalny",
    "typ_kbn",
    "jezyk",
    "dyscyplina_naukowa",
    "rodzaj_zrodla",
    "poziom_wydawcy",
    "funkcja_autora",
    "tytul",
    "czas_udostepnienia_openaccess",
)

# Dane wolumenowe udające słowniki — jawnie odrzucane z czytelnym błędem.
SLOWNIKI_WOLUMENOWE: tuple[str, ...] = (
    "konferencja",
    "wydawca",
    "nagroda",
    "seria_wydawnicza",
    "zrodlo",
    "autor",
    "jednostka",
)


# Biała lista prefiksów endpointów, których odpowiedzi wolno cache'ować w
# procesie (:meth:`bpp_mcp.client.BppClient.get_json`). To WYŁĄCZNIE stabilne,
# powtarzalnie odpytywane tabele referencyjne / encje słownikowe (jednostka,
# źródło, wydawca, słowniki). Świadomie POZA whitelistą: rekordy publikacji,
# streszczenia, tabele through-autorów oraz raporty ``recent_*`` — to dane
# zmienne albo jednorazowe, których cache'owanie tylko puchłoby i groziło
# staleness. Brak prefiksu na liście ⇒ odpowiedź NIE ląduje w cache, nawet
# przy ``use_cache=True``.
PREFIKSY_CACHOWALNE: frozenset[str] = frozenset(SLOWNIKI) | frozenset(
    {
        "jednostka",
        "zrodlo",
        "wydawca",
        "seria_wydawnicza",
        "konferencja",
        "nagroda",
    }
)


def rozbij_rekord_url(url: str | None) -> tuple[str | None, str | None]:
    """Z ``rekord_url`` (``/szukaj/``) wyłuskaj ``(typ, pk)``.

    Mapę ct→typ budujemy dynamicznie z samego URL-a (segment endpointu),
    NIE z numerycznych ID ContentType (per-instancja). Przykład::

        ".../api/v1/wydawnictwo_ciagle/123/" -> ("wydawnictwo_ciagle", "123")
    """
    if not url:
        return (None, None)
    segmenty = [s for s in url.split("/") if s]
    for i, seg in enumerate(segmenty):
        if seg in CATALOG and i + 1 < len(segmenty):
            return (seg, segmenty[i + 1])
    return (None, None)


def rozbij_tuple_id(surowy: object) -> tuple[int | None, int | None]:
    """Sparsuj identyfikator ``Rekord`` w formacie ``"(6, 123)"`` z ``recent_*``.

    Zwraca ``(content_type_id, pk)`` lub ``(None, None)`` przy złym wejściu.
    """
    if not isinstance(surowy, str):
        return (None, None)
    wnetrze = surowy.strip().strip("()")
    czesci = wnetrze.split(",")
    if len(czesci) != 2:
        return (None, None)
    try:
        return (int(czesci[0]), int(czesci[1]))
    except ValueError:
        return (None, None)
