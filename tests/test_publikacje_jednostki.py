import httpx
import pytest
import respx

from bpp_mcp import tools
from bpp_mcp.client import BppNetworkError
from conftest import API_ROOT


def _odpowiedz(publikacje):
    return {
        "jednostka_id": 1,
        "jednostka_nazwa": "Katedra X",
        "profil_url": "https://bpp.test/bpp/jednostka/katedra-x/",
        "count": len(publikacje),
        "publications": publikacje,
    }


def _publikacja(pk=1):
    return {
        "id": f"(6, {pk})",
        "opis_bibliograficzny": "Opis.",
        "rok": 2022,
        "ostatnio_zmieniony": "2022-01-01T00:00:00Z",
        "url": f"https://bpp.test/bpp/rekord/6/{pk}/",
    }


async def test_publikacje_jednostki_happy(client):
    with respx.mock(base_url=API_ROOT, assert_all_called=False) as mock:
        mock.get("/recent_unit_publications/katedra-x/").respond(
            json=_odpowiedz([_publikacja(1)])
        )
        wynik = await tools.publikacje_jednostki(client, "katedra-x")
    assert wynik["jednostka_nazwa"] == "Katedra X"
    assert len(wynik["publikacje"]) == 1
    assert wynik["publikacje"][0]["content_type_id"] == 6


async def test_publikacje_jednostki_pusty(client):
    with respx.mock(base_url=API_ROOT, assert_all_called=False) as mock:
        mock.get("/recent_unit_publications/1/").respond(json=_odpowiedz([]))
        wynik = await tools.publikacje_jednostki(client, "1")
    assert wynik["publikacje"] == []


async def test_publikacje_jednostki_blad_sieci(client):
    with respx.mock(base_url=API_ROOT, assert_all_called=False) as mock:
        mock.get("/recent_unit_publications/1/").side_effect = httpx.ConnectError(
            "down"
        )
        with pytest.raises(BppNetworkError):
            await tools.publikacje_jednostki(client, "1")
