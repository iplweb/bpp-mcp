import httpx
import pytest
import respx

from bpp_mcp import tools
from bpp_mcp.client import BppError, BppNetworkError
from conftest import API_ROOT


def _pozycja(pk=123, typ="wydawnictwo_ciagle"):
    return {
        "id": f"6-{pk}",
        "tytul_oryginalny": "Tytuł pracy",
        "rok": 2023,
        "opis_bibliograficzny": "Kowalski J. Tytuł pracy. 2023.",
        "rekord_url": f"{API_ROOT}/{typ}/{pk}/",
        "absolute_url": f"https://bpp.test/bpp/rekord/6/{pk}/",
    }


async def test_szukaj_publikacji_happy(client):
    with respx.mock(base_url=API_ROOT, assert_all_called=False) as mock:
        mock.get("/szukaj/").respond(
            json={"count": 1, "next": None, "results": [_pozycja()]}
        )
        wynik = await tools.szukaj_publikacji(client, "nowotwór", limit=25)
    assert wynik["count"] == 1
    poz = wynik["wyniki"][0]
    # typ + pk rozłożone z rekord_url (mapa ct→typ dynamicznie, nie hardkod)
    assert poz["typ"] == "wydawnictwo_ciagle"
    assert poz["pk"] == "123"


async def test_szukaj_publikacji_pusty(client):
    with respx.mock(base_url=API_ROOT, assert_all_called=False) as mock:
        mock.get("/szukaj/").respond(json={"count": 0, "next": None, "results": []})
        wynik = await tools.szukaj_publikacji(client, "xyzzy")
    assert wynik["count"] == 0
    assert wynik["wyniki"] == []


async def test_szukaj_publikacji_blad_sieci(client):
    with respx.mock(base_url=API_ROOT, assert_all_called=False) as mock:
        mock.get("/szukaj/").side_effect = httpx.ConnectError("brak sieci")
        with pytest.raises(BppNetworkError):
            await tools.szukaj_publikacji(client, "cokolwiek")


async def test_szukaj_publikacji_404_degradacja(client):
    with respx.mock(base_url=API_ROOT, assert_all_called=False) as mock:
        mock.get("/szukaj/").respond(status_code=404)
        with pytest.raises(BppError) as exc:
            await tools.szukaj_publikacji(client, "cokolwiek")
    assert "Fazą 0" in str(exc.value)


async def test_szukaj_publikacji_paginacja_wielostronicowa(client):
    strona1 = {
        "count": 3,
        "next": f"{API_ROOT}/szukaj/?q=x&limit=25&offset=2",
        "results": [_pozycja(1), _pozycja(2)],
    }
    strona2 = {
        "count": 3,
        "next": None,
        "results": [_pozycja(3)],
    }
    with respx.mock(base_url=API_ROOT, assert_all_called=False) as mock:
        route = mock.get("/szukaj/")
        route.side_effect = [
            httpx.Response(200, json=strona1),
            httpx.Response(200, json=strona2),
        ]
        wynik = await tools.szukaj_publikacji(client, "x", limit=25)
    assert wynik["count"] == 3
    assert route.call_count == 2
