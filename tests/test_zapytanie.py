"""Testy trzech narzędzi DjangoQL po autoryzowanym API:
``zapytanie_rekord`` / ``zapytanie_autor`` / ``zapytanie_autorzy``
(endpointy ``/api/v1/zapytanie/{rekord,autor,autorzy}/``).

respx przechwytuje ruch httpx — żadnych żywych wywołań. Auth (Bearer) jest
wstrzykiwany przez ``BppClient`` z kontekstu; tu weryfikujemy ścieżkę żądania,
paginację i mapowanie kodów stanu (400/401/403/503) na czytelne błędy.
"""

import httpx
import pytest
import respx

from bpp_mcp import tools
from bpp_mcp.auth import set_current_bearer
from bpp_mcp.client import BppClient, BppError
from bpp_mcp.config import Config
from conftest import API_ROOT


def _rekord(pk=123):
    return {
        "id": f"40-{pk}",
        "tytul_oryginalny": "Tytuł pracy",
        "rok": 2023,
        "opis_bibliograficzny": "Kowalski J. Tytuł pracy. 2023.",
        "rekord_url": f"{API_ROOT}/wydawnictwo_ciagle/{pk}/",
        "absolute_url": f"https://bpp.test/bpp/rekord/40/{pk}/",
    }


def _autor(pk=42):
    return {
        "id": pk,
        "slug": "jan-kowalski",
        "nazwisko": "Kowalski",
        "imiona": "Jan",
        "tytul": "prof.",
        "orcid": "0000-0002-1825-0097",
        "aktualna_jednostka": "Katedra Kardiologii",
        "autor_url": f"{API_ROOT}/autor/{pk}/",
        "absolute_url": f"https://bpp.test/bpp/autor/{pk}/",
    }


def _autorstwo(pk=999):
    return {
        "id": f"17-{pk}",
        "zapisany_jako": "J. Kowalski",
        "kolejnosc": 1,
        "autor_url": f"{API_ROOT}/autor/42/",
        "rekord": {
            "tytul": "Tytuł",
            "rekord_url": f"{API_ROOT}/wydawnictwo_ciagle/123/",
        },
        "typ_odpowiedzialnosci": "aut.",
        "jednostka": "Katedra Kardiologii",
        "dyscyplina": "kardiologia",
    }


# --------------------------------------------------------------------------- #
# Happy path — po jednym per narzędzie (różne endpointy, różne serializery).
# --------------------------------------------------------------------------- #


async def test_zapytanie_rekord_happy(client):
    with respx.mock(base_url=API_ROOT, assert_all_called=False) as mock:
        route = mock.get("/zapytanie/rekord/").respond(
            json={"count": 1, "next": None, "results": [_rekord()]}
        )
        wynik = await tools.zapytanie_rekord(
            client, 'autorzy.autor.nazwisko ~ "Kowalski" and rok = 2023'
        )
    assert wynik["laczna_liczba"] == 1
    assert wynik["zwrocono"] == 1
    assert wynik["wyniki"][0]["tytul_oryginalny"] == "Tytuł pracy"
    # q trafia do query stringa endpointu:
    assert "q=" in str(route.calls[0].request.url)


async def test_zapytanie_autor_happy(client):
    with respx.mock(base_url=API_ROOT, assert_all_called=False) as mock:
        mock.get("/zapytanie/autor/").respond(
            json={"count": 1, "next": None, "results": [_autor()]}
        )
        wynik = await tools.zapytanie_autor(client, 'nazwisko ~ "Kowal"')
    assert wynik["zwrocono"] == 1
    assert wynik["wyniki"][0]["nazwisko"] == "Kowalski"


async def test_zapytanie_autorzy_happy(client):
    with respx.mock(base_url=API_ROOT, assert_all_called=False) as mock:
        mock.get("/zapytanie/autorzy/").respond(
            json={"count": 1, "next": None, "results": [_autorstwo()]}
        )
        wynik = await tools.zapytanie_autorzy(client, "rekord.rok = 2023")
    assert wynik["zwrocono"] == 1
    assert wynik["wyniki"][0]["zapisany_jako"] == "J. Kowalski"


# --------------------------------------------------------------------------- #
# Puste zapytanie i pusty wynik.
# --------------------------------------------------------------------------- #


async def test_zapytanie_puste_q_nie_uderza_w_api(client):
    # Puste/białe ``q`` → pusty wynik BEZ żądania (endpoint i tak zwróciłby []).
    with respx.mock(base_url=API_ROOT, assert_all_called=False) as mock:
        route = mock.get("/zapytanie/rekord/")
        wynik = await tools.zapytanie_rekord(client, "   ")
    assert wynik["zwrocono"] == 0
    assert wynik["wyniki"] == []
    assert route.call_count == 0


async def test_zapytanie_pusta_odpowiedz(client):
    with respx.mock(base_url=API_ROOT, assert_all_called=False) as mock:
        mock.get("/zapytanie/rekord/").respond(
            json={"count": 0, "next": None, "results": []}
        )
        wynik = await tools.zapytanie_rekord(client, "rok = 1300")
    assert wynik["laczna_liczba"] == 0
    assert wynik["wyniki"] == []


# --------------------------------------------------------------------------- #
# Mapowanie kodów stanu na czytelne błędy.
# --------------------------------------------------------------------------- #


async def test_zapytanie_400_zle_pole_daje_pozycje(client):
    # 400 z DjangoQL niesie {error,line,column,mark} — mapujemy na komunikat
    # z pozycją, żeby agent mógł poprawić zapytanie.
    with respx.mock(base_url=API_ROOT, assert_all_called=False) as mock:
        mock.get("/zapytanie/rekord/").respond(
            status_code=400,
            json={
                "error": "Unknown field: autor.email",
                "line": 1,
                "column": 6,
                "mark": "token",
            },
        )
        with pytest.raises(BppError) as exc:
            await tools.zapytanie_rekord(client, 'autor.email = "x"')
    msg = str(exc.value)
    assert "Unknown field: autor.email" in msg
    assert "linia 1" in msg and "kolumna 6" in msg


async def test_zapytanie_401_zly_token(client):
    with respx.mock(base_url=API_ROOT, assert_all_called=False) as mock:
        mock.get("/zapytanie/rekord/").respond(
            status_code=401, json={"detail": "Nieprawidłowy token."}
        )
        with pytest.raises(BppError) as exc:
            await tools.zapytanie_rekord(client, "rok = 2023")
    assert "401" in str(exc.value)


async def test_zapytanie_403_brak_uprawnien(client):
    with respx.mock(base_url=API_ROOT, assert_all_called=False) as mock:
        mock.get("/zapytanie/rekord/").respond(
            status_code=403, json={"detail": "Wymagane konto redaktora."}
        )
        with pytest.raises(BppError) as exc:
            await tools.zapytanie_rekord(client, "rok = 2023")
    assert "403" in str(exc.value)


async def test_zapytanie_503_timeout_bez_retry(client):
    # 503 = statement_timeout (deterministyczny) → NIE ponawiamy (inaczej 3×8 s).
    with respx.mock(base_url=API_ROOT, assert_all_called=False) as mock:
        route = mock.get("/zapytanie/rekord/").respond(
            status_code=503,
            json={"error": "Zapytanie trwało za długo — zawęź warunki."},
        )
        with pytest.raises(BppError) as exc:
            await tools.zapytanie_rekord(client, "rok >= 1900")
    assert "zawęź" in str(exc.value).lower() or "za długo" in str(exc.value).lower()
    assert route.call_count == 1  # brak ponawiania 5xx dla zapytań


# --------------------------------------------------------------------------- #
# Paginacja i offset.
# --------------------------------------------------------------------------- #


async def test_zapytanie_paginacja_wielostronicowa(client):
    strona1 = {
        "count": 3,
        "next": f"{API_ROOT}/zapytanie/rekord/?q=rok+%3D+2023&limit=50&offset=50",
        "results": [_rekord(1), _rekord(2)],
    }
    strona2 = {"count": 3, "next": None, "results": [_rekord(3)]}
    with respx.mock(base_url=API_ROOT, assert_all_called=False) as mock:
        route = mock.get("/zapytanie/rekord/")
        route.side_effect = [
            httpx.Response(200, json=strona1),
            httpx.Response(200, json=strona2),
        ]
        wynik = await tools.zapytanie_rekord(client, "rok = 2023", limit=100)
    assert wynik["laczna_liczba"] == 3
    assert wynik["zwrocono"] == 3
    assert route.call_count == 2


async def test_zapytanie_przekazuje_offset(client):
    with respx.mock(base_url=API_ROOT, assert_all_called=False) as mock:
        route = mock.get("/zapytanie/rekord/").respond(
            json={"count": 0, "next": None, "results": []}
        )
        await tools.zapytanie_rekord(client, "rok = 2023", offset=40)
    assert "offset=40" in str(route.calls[0].request.url)


# --------------------------------------------------------------------------- #
# Kontrakt klienta: status_code na błędzie 4xx + retry_5xx=False.
# --------------------------------------------------------------------------- #


async def test_bpp_error_niesie_status_code_i_payload(client):
    with respx.mock(base_url=API_ROOT, assert_all_called=False) as mock:
        mock.get("/zapytanie/rekord/").respond(
            status_code=400, json={"error": "zła składnia"}
        )
        with pytest.raises(BppError) as exc:
            await client.get_paginated("zapytanie/rekord/", {"q": "!!!"}, 25)
    assert exc.value.status_code == 400
    assert exc.value.payload == {"error": "zła składnia"}


async def test_get_paginated_retry_5xx_false_nie_ponawia(client):
    with respx.mock(base_url=API_ROOT, assert_all_called=False) as mock:
        route = mock.get("/zapytanie/rekord/").respond(status_code=503)
        with pytest.raises(BppError) as exc:
            await client.get_paginated(
                "zapytanie/rekord/", {"q": "rok = 2023"}, 25, retry_5xx=False
            )
    assert exc.value.status_code == 503
    assert route.call_count == 1


@respx.mock
async def test_zapytanie_401_stdio_podpowiada_login():
    cfg = Config(base_url="https://bpp.test", transport="stdio")
    respx.get(url__regex=r".*/zapytanie/rekord/.*").mock(
        return_value=httpx.Response(401, json={"detail": "x"})
    )
    async with BppClient(cfg, backoff_base=0.0) as c:
        with pytest.raises(BppError) as ei:
            await tools.zapytanie_rekord(c, "rok = 2026")
    assert ei.value.status_code == 401
    assert "bpp-mcp login" in str(ei.value)


@respx.mock
async def test_zapytanie_401_http_bez_podpowiedzi_login():
    cfg = Config(base_url="https://bpp.test", transport="http")
    respx.get(url__regex=r".*/zapytanie/rekord/.*").mock(
        return_value=httpx.Response(401, json={"detail": "x"})
    )
    # w http _auth_kwargs wymaga bearera, by w ogóle dojść do 401 z serwera:
    set_current_bearer("DUMMY")
    try:
        async with BppClient(cfg, backoff_base=0.0) as c:
            with pytest.raises(BppError) as ei:
                await tools.zapytanie_rekord(c, "rok = 2026")
        assert ei.value.status_code == 401
        assert "bpp-mcp login" not in str(ei.value)
    finally:
        set_current_bearer(None)
