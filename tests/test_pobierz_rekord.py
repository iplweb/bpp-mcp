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


async def test_pobierz_rekord_patent(client):
    """Patent: autorzy przez tabelę through, pola rodzaj_prawa/zasieg inline."""
    detal = {
        "id": 300,
        "tytul_oryginalny": "Sposób wytwarzania X",
        "autorzy_set": [f"{API_ROOT}/patent_autor/1/"],
        "rodzaj_prawa": "patent",
        "zasieg": "krajowy",
    }
    with respx.mock(base_url=API_ROOT, assert_all_called=False) as mock:
        mock.get("/patent/300/").respond(json=detal)
        mock.get("/patent_autor/1/").respond(
            json={
                "id": 1,
                "zapisany_jako": "Kowalski Jan",
                "typ_odpowiedzialnosci": "autor",
                "kolejnosc": 0,
                "autor": f"{API_ROOT}/autor/5/",
                "jednostka": None,
                "dyscyplina_naukowa": None,
            }
        )
        autor_detail = mock.get("/autor/5/").respond(json={"id": 5})
        wynik = await tools.pobierz_rekord(client, "patent", "300")
    # domyślnie bez hopu do autor-detail
    assert autor_detail.call_count == 0
    assert wynik["typ"] == "patent"
    assert wynik["rodzaj_prawa"] == "patent"
    assert wynik["autorzy_set"][0]["zapisany_jako"] == "Kowalski Jan"
    assert wynik["autorzy_set"][0]["autor_url"] == f"{API_ROOT}/autor/5/"


async def test_pobierz_rekord_praca_doktorska(client):
    """Praca dr: brak tabeli through — rozwijamy pojedyncze autor/promotor/
    jednostka/wydawca (gałąź relacje_pojedyncze)."""
    detal = {
        "id": 400,
        "tytul_oryginalny": "Rozprawa doktorska",
        "autor": f"{API_ROOT}/autor/5/",
        "promotor": f"{API_ROOT}/autor/9/",
        "jednostka": f"{API_ROOT}/jednostka/1/",
        "wydawca": f"{API_ROOT}/wydawca/2/",
    }
    with respx.mock(base_url=API_ROOT, assert_all_called=False) as mock:
        mock.get("/praca_doktorska/400/").respond(json=detal)
        mock.get("/autor/5/").respond(json={"id": 5, "nazwisko": "Doktorant"})
        mock.get("/autor/9/").respond(json={"id": 9, "nazwisko": "Promotor"})
        mock.get("/jednostka/1/").respond(json={"id": 1, "nazwa": "Katedra"})
        mock.get("/wydawca/2/").respond(json={"id": 2, "nazwa": "Wydawnictwo"})
        wynik = await tools.pobierz_rekord(client, "praca_doktorska", "400")
    assert wynik["typ"] == "praca_doktorska"
    assert wynik["autor"]["nazwisko"] == "Doktorant"
    assert wynik["promotor"]["nazwisko"] == "Promotor"
    assert wynik["jednostka"]["nazwa"] == "Katedra"
    assert wynik["wydawca"]["nazwa"] == "Wydawnictwo"


async def test_pobierz_rekord_praca_habilitacyjna(client):
    """Praca hab: pojedynczy autor + jednostka + wydawca (bez promotora)."""
    detal = {
        "id": 500,
        "tytul_oryginalny": "Rozprawa habilitacyjna",
        "autor": f"{API_ROOT}/autor/7/",
        "jednostka": f"{API_ROOT}/jednostka/3/",
        "wydawca": f"{API_ROOT}/wydawca/4/",
    }
    with respx.mock(base_url=API_ROOT, assert_all_called=False) as mock:
        mock.get("/praca_habilitacyjna/500/").respond(json=detal)
        mock.get("/autor/7/").respond(json={"id": 7, "nazwisko": "Habilitant"})
        mock.get("/jednostka/3/").respond(json={"id": 3, "nazwa": "Zakład"})
        mock.get("/wydawca/4/").respond(json={"id": 4, "nazwa": "Oficyna"})
        wynik = await tools.pobierz_rekord(client, "praca_habilitacyjna", "500")
    assert wynik["typ"] == "praca_habilitacyjna"
    assert wynik["autor"]["nazwisko"] == "Habilitant"
    assert wynik["wydawca"]["nazwa"] == "Oficyna"


async def test_pobierz_rekord_odrzuca_niepoprawny_id(client):
    # id="../autor/5" nie może skleić path-traversal URL-a — walidacja (D5).
    with pytest.raises(BppError) as exc:
        await tools.pobierz_rekord(client, "wydawnictwo_ciagle", "../autor/5")
    assert "identyfikator" in str(exc.value).lower()


async def test_pobierz_rekord_odrzuca_cyfre_unicode(client):
    # "٣" (arabsko-indyjska 3) ma isdigit()==True, ale nie jest ASCII 0-9 —
    # nie może trafić do URL-a. Walidacja wymusza czyste ASCII (B3).
    with pytest.raises(BppError) as exc:
        await tools.pobierz_rekord(client, "wydawnictwo_ciagle", "١٢٣")
    assert "identyfikator" in str(exc.value).lower()


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
