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
    # Wskazówka kieruje do WYKONANIA zapytania właściwym narzędziem.
    assert "zapytanie_rekord" in wynik["jak_zlozyc"]


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


async def test_djangoql_schema_korzen_autor():
    wynik = await tools.djangoql_schema("autor")
    assert wynik["model"] == "autor"
    assert "# Model: bpp.Autor" in wynik["schemat"]
    assert "start model: bpp.autor" in wynik["schemat"]


async def test_djangoql_schema_korzen_autorzy():
    wynik = await tools.djangoql_schema("autorzy")
    assert wynik["model"] == "autorzy"
    assert "start model: bpp.autorzy" in wynik["schemat"]


async def test_djangoql_schema_trzy_korzenie_dostepne():
    for model in ("rekord", "autor", "autorzy"):
        schemat = (await tools.djangoql_schema(model))["schemat"]
        assert schemat.startswith("# BPP"), model
        assert "dictionaries" in schemat, model


async def test_zasoby_autor_autorzy_spakowane():
    for fname in (
        "autor_djangoql_schema.compact.txt",
        "autorzy_djangoql_schema.compact.txt",
    ):
        zasob = resources.files("bpp_mcp").joinpath("data", fname)
        assert zasob.is_file(), fname
        assert zasob.read_text(encoding="utf-8").startswith("# BPP")


def test_zasob_danych_jest_spakowany():
    # importlib.resources znajduje plik jako dane pakietu (nie ścieżka względna)
    # — dowód, że zasób jest częścią dystrybucji ``bpp_mcp``.
    zasob = resources.files("bpp_mcp").joinpath(
        "data", "rekord_djangoql_schema.compact.txt"
    )
    assert zasob.is_file()
    assert zasob.read_text(encoding="utf-8").startswith("# BPP")


# --- Porcjowanie: rdzeń domyślnie, sekcje na żądanie -----------------------


def _caly_plik(nazwa: str) -> str:
    return (
        resources.files("bpp_mcp").joinpath("data", nazwa).read_text(encoding="utf-8")
    )


async def test_djangoql_schema_domyslnie_zwraca_rdzen():
    schemat = (await tools.djangoql_schema())["schemat"]
    # Rdzeń = preambuła + sekcja modelu-korzenia + słowniki…
    assert schemat.startswith("# BPP")
    assert "start model: bpp.rekord" in schemat
    assert "\nbpp.rekord:\n" in schemat
    assert "dictionaries" in schemat
    # …i NIC ponadto: sekcje modeli relacyjnych zostają poza rdzeniem.
    assert "\nbpp.zrodlo:\n" not in schemat
    assert "\nbpp.jednostka:\n" not in schemat


async def test_djangoql_schema_rdzen_duzo_mniejszy_od_pliku():
    for model, nazwa_pliku in (
        ("rekord", "rekord_djangoql_schema.compact.txt"),
        ("autor", "autor_djangoql_schema.compact.txt"),
        ("autorzy", "autorzy_djangoql_schema.compact.txt"),
    ):
        rdzen = (await tools.djangoql_schema(model))["schemat"]
        caly = _caly_plik(nazwa_pliku)
        assert rdzen.strip(), model
        # Powód całej tej roboty: cały plik przebijał sufit wyniku MCP.
        assert len(rdzen) < 0.4 * len(caly), model


async def test_djangoql_schema_jedna_sekcja_bez_rdzenia():
    wynik = await tools.djangoql_schema("rekord", sekcje=["bpp.zrodlo"])
    schemat = wynik["schemat"]
    assert schemat.startswith("bpp.zrodlo:")
    # Dobrana sekcja przychodzi SAMA — bez preambuły i bez słowników.
    assert "# BPP" not in schemat
    assert "start model:" not in schemat
    assert "dictionaries" not in schemat


async def test_djangoql_schema_wiele_sekcji_w_kolejnosci_z_pliku():
    # W pliku ``bpp.zrodlo`` leży przed ``bpp.jednostka`` — kolejność argumentów
    # nie ma znaczenia, wynik jest deterministyczny.
    odwrotnie = await tools.djangoql_schema(
        "rekord", sekcje=["bpp.jednostka", "bpp.zrodlo"]
    )
    wprost = await tools.djangoql_schema(
        "rekord", sekcje=["bpp.zrodlo", "bpp.jednostka"]
    )
    assert odwrotnie["schemat"] == wprost["schemat"]
    schemat = wprost["schemat"]
    assert schemat.index("bpp.zrodlo:") < schemat.index("bpp.jednostka:")


async def test_djangoql_schema_pusta_lista_sekcji_to_rdzen():
    pusta = await tools.djangoql_schema("rekord", sekcje=[])
    assert pusta["schemat"] == (await tools.djangoql_schema("rekord"))["schemat"]


async def test_djangoql_schema_nieznana_sekcja_z_podpowiedzia():
    with pytest.raises(BppError) as exc:
        await tools.djangoql_schema("rekord", sekcje=["bpp.zrodla"])
    komunikat = str(exc.value)
    assert "bpp.zrodla" in komunikat
    # difflib podpowiada najbliższą istniejącą nazwę.
    assert "bpp.zrodlo" in komunikat


async def test_djangoql_schema_sekcja_korzenia_odrzucona():
    with pytest.raises(BppError) as exc:
        await tools.djangoql_schema("rekord", sekcje=["bpp.rekord"])
    assert "rdzeni" in str(exc.value)


async def test_djangoql_schema_sekcje_dostepne_w_obu_trybach():
    for wynik in (
        await tools.djangoql_schema("rekord"),
        await tools.djangoql_schema("rekord", sekcje=["bpp.zrodlo"]),
    ):
        dostepne = wynik["sekcje_dostepne"]
        assert isinstance(dostepne, list)
        assert dostepne
        assert "bpp.zrodlo" in dostepne
        # Korzeń i słowniki są już w rdzeniu — nie ma po co ich dobierać.
        assert "bpp.rekord" not in dostepne
        assert "dictionaries" not in dostepne
