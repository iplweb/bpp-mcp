import httpx
import pytest
import respx

from bpp_mcp import tools
from bpp_mcp.client import BppError, BppNetworkError
from conftest import API_ROOT


def _publikacja(pk=123):
    return {
        "id": f"(6, {pk})",
        "opis_bibliograficzny": "Kowalski J. Praca. 2023.",
        "rok": 2023,
        "ostatnio_zmieniony": "2023-01-01T00:00:00Z",
        "url": f"https://bpp.test/bpp/rekord/6/{pk}/",
    }


def _odpowiedz(publikacje):
    return {
        "autor_id": 5,
        "autor_nazwa": "Jan Kowalski",
        "profil_url": "https://bpp.test/bpp/autor/jan-kowalski/",
        "count": len(publikacje),
        "publications": publikacje,
    }


async def test_publikacje_autora_happy(client):
    with respx.mock(base_url=API_ROOT, assert_all_called=False) as mock:
        mock.get("/recent_author_publications/5/").respond(
            json=_odpowiedz([_publikacja(1), _publikacja(2)])
        )
        wynik = await tools.publikacje_autora(client, "5")
    assert wynik["autor_nazwa"] == "Jan Kowalski"
    assert wynik["obcieto"] is False
    # ``count`` z endpointu (len PO obcięciu) NIE przecieka jako mylący total —
    # eksponujemy tylko ``zwrocono`` (B1).
    assert "count" not in wynik
    assert wynik["zwrocono"] == 2
    assert len(wynik["publikacje"]) == 2
    # id "(6, 1)" rozłożone na content_type_id + pk
    assert wynik["publikacje"][0]["content_type_id"] == 6
    assert wynik["publikacje"][0]["pk"] == 1


async def test_publikacje_autora_pusty(client):
    with respx.mock(base_url=API_ROOT, assert_all_called=False) as mock:
        mock.get("/recent_author_publications/brak/").respond(json=_odpowiedz([]))
        wynik = await tools.publikacje_autora(client, "brak")
    assert wynik["publikacje"] == []
    assert wynik["obcieto"] is False


async def test_publikacje_autora_obcieto(client):
    pubs = [_publikacja(i) for i in range(100)]
    with respx.mock(base_url=API_ROOT, assert_all_called=False) as mock:
        mock.get("/recent_author_publications/5/").respond(json=_odpowiedz(pubs))
        wynik = await tools.publikacje_autora(client, "5", limit=100)
    assert wynik["obcieto"] is True
    assert len(wynik["publikacje"]) == 100


async def test_publikacje_autora_404(client):
    with respx.mock(base_url=API_ROOT, assert_all_called=False) as mock:
        mock.get("/recent_author_publications/9/").respond(status_code=404)
        with pytest.raises(BppError) as exc:
            await tools.publikacje_autora(client, "9")
    assert "niewidoczny" in str(exc.value)


async def test_publikacje_autora_blad_sieci(client):
    with respx.mock(base_url=API_ROOT, assert_all_called=False) as mock:
        mock.get("/recent_author_publications/5/").side_effect = httpx.ConnectError(
            "down"
        )
        with pytest.raises(BppNetworkError):
            await tools.publikacje_autora(client, "5")
