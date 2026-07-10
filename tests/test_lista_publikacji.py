import httpx
import pytest
import respx

from bpp_mcp import tools
from bpp_mcp.client import BppError, BppNetworkError
from conftest import API_ROOT


def _rekord(pk):
    return {"id": pk, "tytul_oryginalny": f"Praca {pk}", "rok": 2023}


async def test_lista_publikacji_happy(client):
    with respx.mock(base_url=API_ROOT, assert_all_called=False) as mock:
        route = mock.get("/wydawnictwo_ciagle/").respond(
            json={"count": 2, "next": None, "results": [_rekord(1), _rekord(2)]}
        )
        wynik = await tools.lista_publikacji(
            client, "wydawnictwo_ciagle", rok_od=2020, rok_do=2023, limit=25
        )
    assert wynik["laczna_liczba"] == 2
    assert wynik["zwrocono"] == 2
    assert wynik["typ"] == "wydawnictwo_ciagle"
    # mapowanie filtrów rok_od→rok_min, rok_do→rok_max
    zadanie = route.calls.last.request
    assert zadanie.url.params["rok_min"] == "2020"
    assert zadanie.url.params["rok_max"] == "2023"


async def test_lista_publikacji_pusty(client):
    with respx.mock(base_url=API_ROOT, assert_all_called=False) as mock:
        mock.get("/wydawnictwo_zwarte/").respond(
            json={"count": 0, "next": None, "results": []}
        )
        wynik = await tools.lista_publikacji(client, "wydawnictwo_zwarte")
    assert wynik["zwrocono"] == 0
    assert wynik["wyniki"] == []


async def test_lista_publikacji_paginacja(client):
    strona1 = {
        "count": 3,
        "next": f"{API_ROOT}/wydawnictwo_ciagle/?limit=25&offset=2",
        "results": [_rekord(1), _rekord(2)],
    }
    strona2 = {"count": 3, "next": None, "results": [_rekord(3)]}
    with respx.mock(base_url=API_ROOT, assert_all_called=False) as mock:
        route = mock.get("/wydawnictwo_ciagle/")
        route.side_effect = [
            httpx.Response(200, json=strona1),
            httpx.Response(200, json=strona2),
        ]
        wynik = await tools.lista_publikacji(client, "wydawnictwo_ciagle", limit=25)
    assert wynik["laczna_liczba"] == 3
    assert wynik["zwrocono"] == 3
    assert route.call_count == 2


async def test_lista_publikacji_nieznany_typ(client):
    with pytest.raises(BppError) as exc:
        await tools.lista_publikacji(client, "cos")
    assert "Nieznany typ" in str(exc.value)


async def test_lista_publikacji_clamp_limit(client):
    # limit=1_000_000 → clamp do MAKS_LIMIT (200); paginacja porcjami po 50,
    # bezpiecznik pętli nie zapętla mimo nieskończonego ``next`` (W1 + W5).
    def strona(request):
        offset = int(request.url.params.get("offset", 0))
        return httpx.Response(
            200,
            json={
                "count": 10000,
                "next": f"{API_ROOT}/wydawnictwo_ciagle/?limit=50&offset={offset + 50}",
                "results": [{"id": offset + i} for i in range(50)],
            },
        )

    with respx.mock(base_url=API_ROOT, assert_all_called=False) as mock:
        route = mock.get("/wydawnictwo_ciagle/")
        route.side_effect = strona
        wynik = await tools.lista_publikacji(
            client, "wydawnictwo_ciagle", limit=1_000_000
        )
    assert wynik["zwrocono"] == 200  # przycięte do MAKS_LIMIT
    assert wynik["laczna_liczba"] == 10000
    # per-page = 50 → 200 pozycji zebranych w 4 stronach (nie jednym megarequestem)
    assert route.calls[0].request.url.params["limit"] == "50"
    assert route.call_count == 4


async def test_lista_publikacji_odrzuca_charakter_dla_patentu(client):
    # patent nie filtruje charakter_formalny (django-filter cicho ignoruje) →
    # jawny BppError zamiast fałszywie „przefiltrowanego" wyniku (W2).
    with pytest.raises(BppError) as exc:
        await tools.lista_publikacji(client, "patent", charakter_formalny="1")
    assert "charakter_formalny" in str(exc.value)


async def test_lista_publikacji_charakter_dla_ciaglego_przechodzi(client):
    # Kontrola pozytywna: dla wydawnictwo_ciagle filtr trafia do zapytania.
    with respx.mock(base_url=API_ROOT, assert_all_called=False) as mock:
        route = mock.get("/wydawnictwo_ciagle/").respond(
            json={"count": 0, "next": None, "results": []}
        )
        await tools.lista_publikacji(
            client, "wydawnictwo_ciagle", charakter_formalny="7"
        )
    assert route.calls.last.request.url.params["charakter_formalny"] == "7"


async def test_lista_publikacji_blad_sieci(client):
    with respx.mock(base_url=API_ROOT, assert_all_called=False) as mock:
        mock.get("/wydawnictwo_ciagle/").side_effect = httpx.ConnectError("x")
        with pytest.raises(BppNetworkError):
            await tools.lista_publikacji(client, "wydawnictwo_ciagle")
