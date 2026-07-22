"""Parser zbundlowanego schematu DjangoQL-dla-LLM (format ``compact``).

Czysty tekst → :class:`Schemat`: preambuła, sekcje modeli w kolejności z pliku
oraz blok ``dictionaries``. Bez I/O, bez sieci, bez zależności od
:mod:`bpp_mcp.tools` — wczytywanie zasobu i mapowanie błędów na ``BppError``
robi warstwa narzędzia, tutaj lecą zwykłe ``ValueError``.

Powód istnienia: ``djangoql_schema`` nie może oddawać całego pliku (74 kB
przebija sufit wyniku narzędzia MCP), więc kroi go na rdzeń (preambuła +
sekcja modelu-korzenia + słowniki) i sekcje dobierane na żądanie.

Format pliku (generator ``opisz_schemat_djangoql_dla_llm`` w głównym BPP):

* preambuła — od początku pliku do pierwszego nagłówka sekcji; zawiera linię
  ``start model: <nazwa>``, z której wyprowadzamy korzeń,
* nagłówek sekcji — linia ``^[a-z_]+\\.[a-z_]+:$`` w kolumnie 0
  (np. ``bpp.rekord:``), zawartość sekcji jest wcięta,
* ``dictionaries`` — linia zaczynająca się od ``dictionaries`` w kolumnie 0,
  blok ciągnie się do końca pliku.

Dryf tego formatu ma kończyć się głośną awarią (patrz guardy w
:func:`podziel` i :func:`rdzen` oraz test kontraktu formatu), nie cichym
zwrotem pustego schematu — model dostawszy pusty schemat zacząłby zgadywać
nazwy pól.
"""

from __future__ import annotations

import difflib
import re
from collections.abc import Sequence
from dataclasses import dataclass

# Nagłówek sekcji modelu: ``app_label.model_name:`` w kolumnie 0.
_RE_NAGLOWEK = re.compile(r"^[a-z_]+\.[a-z_]+:$")

# Linia wskazująca model-korzeń. Nazwy nie hardkodujemy — bierzemy ją z pliku.
_RE_START_MODEL = re.compile(r"^start model:\s*(\S+)\s*$", re.MULTILINE)

# Nazwa (klucz) bloku słowników — nie jest zwykłą sekcją modelu.
NAZWA_SLOWNIKOW = "dictionaries"


@dataclass(frozen=True)
class Schemat:
    """Rozłożony na części schemat DjangoQL jednego korzenia."""

    preambula: str
    """Od początku pliku do pierwszego nagłówka sekcji (reguły języka)."""

    korzen: str
    """Nazwa modelu-korzenia bez dwukropka, np. ``bpp.rekord``."""

    sekcje: dict[str, str]
    """Nazwa modelu → blok tekstu WRAZ z linią nagłówka, w kolejności z pliku."""

    slowniki: str
    """Blok ``dictionaries (...)`` do końca pliku."""


def podziel(tekst: str) -> Schemat:
    """Rozłóż tekst schematu na preambułę, sekcje modeli i blok słowników.

    Bloki zwracane są bez końcowych pustych linii (``rstrip``), żeby sklejanie
    ``"\\n\\n".join(...)`` dawało przewidywalne odstępy.

    :raises ValueError: gdy brak linii ``start model:`` albo gdy wskazany
        przez nią korzeń nie ma odpowiadającej sekcji (dryf formatu).
    """
    linie = tekst.split("\n")

    # Granice: indeksy nagłówków sekcji oraz początek bloku ``dictionaries``.
    indeksy_naglowkow: list[int] = []
    indeks_slownikow: int | None = None
    for i, linia in enumerate(linie):
        if indeks_slownikow is None and linia.startswith(NAZWA_SLOWNIKOW):
            indeks_slownikow = i
            # Wszystko poniżej należy już do słowników — nawet gdyby wyglądało
            # jak nagłówek sekcji.
            break
        if _RE_NAGLOWEK.match(linia):
            indeksy_naglowkow.append(i)

    koniec_tresci = indeks_slownikow if indeks_slownikow is not None else len(linie)

    # Preambuła kończy się na pierwszej granicy — nagłówku sekcji albo (gdyby
    # sekcji nie było wcale) na bloku słowników.
    pierwsza_granica = indeksy_naglowkow[0] if indeksy_naglowkow else koniec_tresci
    preambula = "\n".join(linie[:pierwsza_granica]).rstrip()

    sekcje: dict[str, str] = {}
    for kolejnosc, poczatek in enumerate(indeksy_naglowkow):
        nastepny = indeksy_naglowkow[kolejnosc + 1 :]
        koniec = nastepny[0] if nastepny else koniec_tresci
        nazwa = linie[poczatek].rstrip(":")
        sekcje[nazwa] = "\n".join(linie[poczatek:koniec]).rstrip()

    slowniki = (
        "\n".join(linie[indeks_slownikow:]).rstrip()
        if indeks_slownikow is not None
        else ""
    )

    dopasowanie = _RE_START_MODEL.search(preambula)
    if dopasowanie is None:
        raise ValueError(
            "Schemat bez linii `start model:` — format pliku schematu "
            "DjangoQL zmienił się albo plik jest uszkodzony."
        )
    korzen = dopasowanie.group(1).rstrip(":")

    if korzen not in sekcje:
        raise ValueError(
            f"Schemat wskazuje korzeń `{korzen}`, ale nie ma sekcji o tej "
            f"nazwie (znaleziono {len(sekcje)} sekcji) — format pliku "
            "schematu DjangoQL zmienił się albo plik jest uszkodzony."
        )

    return Schemat(preambula=preambula, korzen=korzen, sekcje=sekcje, slowniki=slowniki)


def rdzen(s: Schemat) -> str:
    """Zwróć rdzeń: preambuła + sekcja modelu-korzenia + słowniki.

    :raises ValueError: gdy brak sekcji korzenia albo gdy wynik byłby pusty
        (bezpiecznik przed cichym zwrotem pustego schematu).
    """
    if s.korzen not in s.sekcje:
        raise ValueError(
            f"Brak sekcji modelu-korzenia `{s.korzen}` w schemacie — format "
            "pliku schematu DjangoQL zmienił się albo plik jest uszkodzony."
        )

    czesci = [czesc for czesc in (s.preambula, s.sekcje[s.korzen], s.slowniki) if czesc]
    wynik = "\n\n".join(czesci) + "\n"
    if not wynik.strip():
        raise ValueError(
            "Rdzeń schematu wyszedł pusty — format pliku schematu DjangoQL "
            "zmienił się albo plik jest uszkodzony."
        )
    return wynik


def wytnij(s: Schemat, nazwy: Sequence[str]) -> str:
    """Skleij wskazane sekcje modeli — zawsze w kolejności z pliku.

    Duplikaty są pomijane, kolejność argumentów nie ma znaczenia (wynik jest
    deterministyczny).

    :raises ValueError: gdy nie podano żadnej nazwy, gdy podano nazwę sekcji
        korzenia albo ``dictionaries`` (są już w rdzeniu), albo gdy któraś
        nazwa jest nieznana (komunikat wymienia WSZYSTKIE nieznane wraz z
        najbliższymi dopasowaniami).
    """
    # Deduplikacja z zachowaniem kolejności zgłoszeń — tylko na potrzeby
    # komunikatów o błędach; wynik i tak idzie w kolejności z pliku.
    zadane = list(dict.fromkeys(nazwy))

    if not zadane:
        raise ValueError(
            "Nie podano nazw sekcji do wycięcia — wywołaj bez parametru "
            "sekcje, żeby dostać rdzeń schematu."
        )

    w_rdzeniu = [n for n in zadane if n == s.korzen or n == NAZWA_SLOWNIKOW]
    if w_rdzeniu:
        raise ValueError(
            f"Sekcje {', '.join(w_rdzeniu)} są już w rdzeniu schematu "
            "(preambuła + sekcja modelu-korzenia + dictionaries) — wystarczy "
            "wywołać bez parametru sekcje."
        )

    nieznane = [n for n in zadane if n not in s.sekcje]
    if nieznane:
        raise ValueError(_komunikat_nieznane(s, nieznane))

    szukane = set(zadane)
    wybrane = [blok for nazwa, blok in s.sekcje.items() if nazwa in szukane]
    return "\n\n".join(wybrane) + "\n"


def _komunikat_nieznane(s: Schemat, nieznane: Sequence[str]) -> str:
    """Złóż komunikat o nieznanych sekcjach — wszystkie naraz, każda z
    najbliższymi dopasowaniami (``difflib``), plus liczba dostępnych sekcji.
    Chodzi o to, żeby model poprawił literówkę bez dodatkowej rundy wywołań."""
    dostepne = [n for n in s.sekcje if n != s.korzen]
    czesci = []
    for nazwa in nieznane:
        bliskie = difflib.get_close_matches(nazwa, dostepne, n=3)
        if bliskie:
            czesci.append(f"{nazwa} (może chodziło o: {', '.join(bliskie)}?)")
        else:
            czesci.append(nazwa)
    return (
        f"Nieznane sekcje schematu: {'; '.join(czesci)}. "
        f"Dostępnych sekcji: {len(dostepne)} — ich nazwy są w polu "
        "sekcje_dostepne zwrotu narzędzia."
    )
