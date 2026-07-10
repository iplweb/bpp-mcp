import httpx
import pytest
import respx

from bpp_mcp import tools
from bpp_mcp.client import BppError, BppNetworkError
from conftest import API_ROOT


def _detal_ciagle():
    return {
        "id": 100,
        "tytul_oryginalny": "Praca ciągła",
        "rok": 2023,
        "autorzy_set": [
            f"{API_ROOT}/wydawnictwo_ciagle_autor/11/",
            f"{API_ROOT}/wydawnictwo_ciagle_autor/10/",
        ],
        "zrodlo": f"{API_ROOT}/zrodlo/7/",
        "streszczenia": [f"{API_ROOT}/wydawnictwo_ciagle_streszczenie/3/"],
        "zewnetrzna_baza_danych": [],
    }


def _through(pk, kolejnosc, zapisany, autor_pk):
    return {
        "id": pk,
        "zapisany_jako": zapisany,
        "typ_odpowiedzialnosci": "autor",
        "kolejnosc": kolejnosc,
        "afiliuje": True,
        "procent": None,
        "autor": f"{API_ROOT}/autor/{autor_pk}/",
        "jednostka": f"{API_ROOT}/jednostka/1/",
        "dyscyplina_naukowa": None,
    }


def _zamockuj_ciagle(mock):
    mock.get("/wydawnictwo_ciagle/100/").respond(json=_detal_ciagle())
    mock.get("/wydawnictwo_ciagle_autor/10/").respond(
        json=_through(10, 0, "Kowalski Jan", 5)
    )
    mock.get("/wydawnictwo_ciagle_autor/11/").respond(
        json=_through(11, 1, "Nowak Anna", 6)
    )
    mock.get("/zrodlo/7/").respond(json={"id": 7, "nazwa": "Journal of Testing"})
    mock.get("/wydawnictwo_ciagle_streszczenie/3/").respond(
        json={"streszczenie": "Abstrakt.", "jezyk_streszczenia": "pol"}
    )


async def test_pobierz_rekord_buduje_autorow_bez_autor_detail(client):
    """Domyślnie: zapisany_jako z rekordu through, BEZ hopu do autor-detail."""
    with respx.mock(base_url=API_ROOT, assert_all_called=False) as mock:
        _zamockuj_ciagle(mock)
        autor_detail = mock.get("/autor/5/").respond(json={"id": 5})
        autor_detail6 = mock.get("/autor/6/").respond(json={"id": 6})
        wynik = await tools.pobierz_rekord(client, "wydawnictwo_ciagle", "100")

    # autor-detail NIE został zawołany (kluczowa asercja polityki głębokości)
    assert autor_detail.call_count == 0
    assert autor_detail6.call_count == 0

    autorzy = wynik["autorzy_set"]
    assert [a["kolejnosc"] for a in autorzy] == [0, 1]  # posortowane
    assert autorzy[0]["zapisany_jako"] == "Kowalski Jan"
    assert autorzy[0]["autor_url"] == f"{API_ROOT}/autor/5/"
    assert "autor" not in autorzy[0]  # brak pełnego profilu domyślnie

    assert wynik["zrodlo"]["nazwa"] == "Journal of Testing"
    assert wynik["streszczenia"][0]["streszczenie"] == "Abstrakt."
    assert wynik["typ"] == "wydawnictwo_ciagle"


async def test_pobierz_rekord_pelne_dane_autorow(client):
    with respx.mock(base_url=API_ROOT, assert_all_called=False) as mock:
        _zamockuj_ciagle(mock)
        autor_detail = mock.get("/autor/5/").respond(
            json={"id": 5, "nazwisko": "Kowalski"}
        )
        mock.get("/autor/6/").respond(json={"id": 6, "nazwisko": "Nowak"})
        wynik = await tools.pobierz_rekord(
            client, "wydawnictwo_ciagle", "100", pelne_dane_autorow=True
        )
    assert autor_detail.call_count == 1
    autor0 = wynik["autorzy_set"][0]
    assert autor0["autor"]["nazwisko"] == "Kowalski"


async def test_pobierz_rekord_zwarte_bez_zrodla(client):
    """Wydawnictwo zwarte nie ma relacji zrodlo — rozwijamy serię, nie źródło."""
    detal = {
        "id": 200,
        "tytul_oryginalny": "Książka",
        "autorzy_set": [],
        "seria_wydawnicza": f"{API_ROOT}/seria_wydawnicza/2/",
        "streszczenia": [],
        "wydawnictwo_nadrzedne": f"{API_ROOT}/wydawnictwo_zwarte/1/",
    }
    with respx.mock(base_url=API_ROOT, assert_all_called=False) as mock:
        mock.get("/wydawnictwo_zwarte/200/").respond(json=detal)
        seria = mock.get("/seria_wydawnicza/2/").respond(
            json={"id": 2, "nazwa": "Seria A"}
        )
        nadrzedne = mock.get("/wydawnictwo_zwarte/1/").respond(json={"id": 1})
        wynik = await tools.pobierz_rekord(client, "wydawnictwo_zwarte", "200")
    assert seria.call_count == 1
    # wydawnictwo_nadrzedne świadomie NIE rozwijane (pozostaje URL-em)
    assert nadrzedne.call_count == 0
    assert wynik["seria_wydawnicza"]["nazwa"] == "Seria A"
    assert wynik["wydawnictwo_nadrzedne"] == f"{API_ROOT}/wydawnictwo_zwarte/1/"


async def test_pobierz_rekord_nieznany_typ(client):
    with pytest.raises(BppError) as exc:
        await tools.pobierz_rekord(client, "cos_dziwnego", "1")
    assert "Nieznany typ" in str(exc.value)


async def test_pobierz_rekord_404(client):
    with respx.mock(base_url=API_ROOT, assert_all_called=False) as mock:
        mock.get("/wydawnictwo_ciagle/999/").respond(status_code=404)
        with pytest.raises(BppError):
            await tools.pobierz_rekord(client, "wydawnictwo_ciagle", "999")


async def test_pobierz_rekord_blad_sieci(client):
    with respx.mock(base_url=API_ROOT, assert_all_called=False) as mock:
        mock.get("/wydawnictwo_ciagle/100/").side_effect = httpx.ConnectError("x")
        with pytest.raises(BppNetworkError):
            await tools.pobierz_rekord(client, "wydawnictwo_ciagle", "100")
