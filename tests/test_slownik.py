import httpx
import pytest
import respx

from bpp_mcp import tools
from bpp_mcp.client import BppError, BppNetworkError
from conftest import API_ROOT


async def test_slownik_happy(client):
    with respx.mock(base_url=API_ROOT, assert_all_called=False) as mock:
        route = mock.get("/charakter_formalny/").respond(
            json={
                "count": 2,
                "next": None,
                "results": [
                    {"id": 1, "nazwa": "Artykuł", "skrot": "AR"},
                    {"id": 2, "nazwa": "Książka", "skrot": "KS"},
                ],
            }
        )
        wynik = await tools.slownik(client, "charakter_formalny")
    assert wynik["rodzaj"] == "charakter_formalny"
    assert wynik["count"] == 2
    # jedno żądanie z ?limit=500
    assert route.calls.last.request.url.params["limit"] == "500"


async def test_slownik_pusty(client):
    with respx.mock(base_url=API_ROOT, assert_all_called=False) as mock:
        mock.get("/jezyk/").respond(json={"count": 0, "next": None, "results": []})
        wynik = await tools.slownik(client, "jezyk")
    assert wynik["count"] == 0
    assert wynik["pozycje"] == []


async def test_slownik_odrzuca_wolumenowy(client):
    # konferencja/wydawca/nagroda to dane wolumenowe — bez żądania sieciowego.
    for rodzaj in ("konferencja", "wydawca", "nagroda"):
        with pytest.raises(BppError) as exc:
            await tools.slownik(client, rodzaj)
        assert "wolumenowe" in str(exc.value)


async def test_slownik_nieznany(client):
    with pytest.raises(BppError) as exc:
        await tools.slownik(client, "cos_dziwnego")
    assert "Nieznany słownik" in str(exc.value)


async def test_slownik_blad_sieci(client):
    with respx.mock(base_url=API_ROOT, assert_all_called=False) as mock:
        mock.get("/jezyk/").side_effect = httpx.ConnectError("x")
        with pytest.raises(BppNetworkError):
            await tools.slownik(client, "jezyk")
