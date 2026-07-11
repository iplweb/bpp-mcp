"""Testy narzędzia ``djangoql_schema()`` — zwraca zbundlowany, lokalny zasób
(schemat DjangoQL-dla-LLM). Zasób NIE wymaga sieci (respx zbędny)."""

from importlib import resources

import pytest

from bpp_mcp import tools
from bpp_mcp.client import BppError
from bpp_mcp.server import PROMPT_ZLOZ_ZAPYTANIE, zloz_zapytanie_djangoql


async def test_djangoql_schema_zwraca_naglowek_i_slowniki():
    wynik = await tools.djangoql_schema()
    assert wynik["model"] == "rekord"
    schemat = wynik["schemat"]
    assert isinstance(schemat, str)
    assert schemat.strip()  # niepusty
    # Nagłówek z wersją BPP oraz sekcja dozwolonych wartości słownikowych.
    assert "# BPP" in schemat
    assert "dictionaries" in schemat
    # Reguły języka DjangoQL (gramatyka) też są w nagłówku.
    assert "DjangoQL schema" in schemat


async def test_djangoql_schema_zawiera_wskazowke_jak_zlozyc():
    wynik = await tools.djangoql_schema()
    assert isinstance(wynik["jak_zlozyc"], str)
    assert "operator" in wynik["jak_zlozyc"]
    assert "dictionaries" in wynik["jak_zlozyc"]
    assert "wklej" in wynik["jak_zlozyc"]


def test_prompt_zloz_zapytanie_wplata_opis_i_reguly():
    opis = "publikacje po angielsku z 2023 z impact factorem"
    wiadomosc = zloz_zapytanie_djangoql(opis)
    assert isinstance(wiadomosc, str)
    assert wiadomosc.strip()
    # Opis użytkownika jest wpleciony w instrukcję.
    assert opis in wiadomosc
    # Kluczowe reguły kompozycji obecne.
    assert "djangoql_schema" in wiadomosc
    assert "operator" in wiadomosc
    assert "dictionaries" in wiadomosc
    assert "wklej" in wiadomosc


def test_prompt_stala_ma_placeholder_opis():
    # Treść trzymana jako jedna stała modułowa z jednym miejscem interpolacji.
    assert "{opis}" in PROMPT_ZLOZ_ZAPYTANIE


async def test_djangoql_schema_domyslny_model_to_rekord():
    assert (await tools.djangoql_schema())["schemat"] == (
        await tools.djangoql_schema("rekord")
    )["schemat"]


async def test_djangoql_schema_nieznany_model():
    with pytest.raises(BppError) as exc:
        await tools.djangoql_schema("nie_ma_takiego")
    assert "Nieznany model" in str(exc.value)


def test_zasob_danych_jest_spakowany():
    # importlib.resources znajduje plik jako dane pakietu (nie ścieżka względna)
    # — dowód, że zasób jest częścią dystrybucji ``bpp_mcp``.
    zasob = resources.files("bpp_mcp").joinpath(
        "data", "rekord_djangoql_schema.compact.txt"
    )
    assert zasob.is_file()
    assert zasob.read_text(encoding="utf-8").startswith("# BPP")
