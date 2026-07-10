import httpx
import pytest
import respx

from bpp_mcp import tools
from bpp_mcp.client import BppNetworkError
from conftest import API_ROOT


def _autor(pk=5):
    return {
        "id": pk,
        "nazwisko": "Kowalski",
        "imiona": "Jan",
        "slug": f"jan-kowalski-{pk}",
        "aktualna_jednostka": f"{API_ROOT}/jednostka/1/",
    }


async def test_szukaj_autora_happy(client):
    with respx.mock(base_url=API_ROOT, assert_all_called=False) as mock:
        mock.get("/autor/").respond(
            json={"count": 1, "next": None, "results": [_autor()]}
        )
        wynik = await tools.szukaj_autora(client, "kowalski")
    assert wynik["count"] == 1
    assert wynik["mozliwe_ze_niefiltrowane"] is False
    assert wynik["autorzy"][0]["nazwisko"] == "Kowalski"


async def test_szukaj_autora_pusty(client):
    with respx.mock(base_url=API_ROOT, assert_all_called=False) as mock:
        mock.get("/autor/").respond(json={"count": 0, "next": None, "results": []})
        wynik = await tools.szukaj_autora(client, "nieistnieje")
    assert wynik["count"] == 0
    assert wynik["autorzy"] == []


async def test_szukaj_autora_blad_sieci(client):
    with respx.mock(base_url=API_ROOT, assert_all_called=False) as mock:
        mock.get("/autor/").side_effect = httpx.ConnectError("down")
        with pytest.raises(BppNetworkError):
            await tools.szukaj_autora(client, "kowalski")


async def test_szukaj_autora_flaga_niefiltrowane(client):
    # Stara instancja bez Fazy 0 ignoruje ?nazwisko= i zwraca WSZYSTKICH →
    # dobicie do sufitu 100 podnosi flagę ostrzegawczą.
    strona = {
        "count": 500,
        "next": None,
        "results": [_autor(i) for i in range(100)],
    }
    with respx.mock(base_url=API_ROOT, assert_all_called=False) as mock:
        mock.get("/autor/").respond(json=strona)
        wynik = await tools.szukaj_autora(client, "k")
    assert wynik["count"] == 100
    assert wynik["mozliwe_ze_niefiltrowane"] is True
