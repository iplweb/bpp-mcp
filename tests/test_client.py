import httpx
import pytest
import respx

from bpp_mcp.client import BppClient, BppError, BppNetworkError, BppNotFound
from bpp_mcp.config import Config
from conftest import API_ROOT, BASE_URL


async def test_retry_na_5xx_potem_sukces():
    client = BppClient(Config(base_url=BASE_URL), max_retries=2, backoff_base=0.0)
    try:
        with respx.mock(base_url=API_ROOT, assert_all_called=False) as mock:
            route = mock.get("/jezyk/")
            route.side_effect = [
                httpx.Response(503),
                httpx.Response(503),
                httpx.Response(200, json={"ok": True}),
            ]
            dane = await client.get_json("jezyk/", use_cache=False)
        assert dane == {"ok": True}
        assert route.call_count == 3
    finally:
        await client.aclose()


async def test_cache_url_json(client):
    with respx.mock(base_url=API_ROOT, assert_all_called=False) as mock:
        route = mock.get("/tytul/").respond(json={"count": 0, "results": []})
        await client.get_json("tytul/")
        await client.get_json("tytul/")
    # drugi odczyt z procesowego cache — bez drugiego żądania
    assert route.call_count == 1


async def test_404_podnosi_bppnotfound(client):
    with respx.mock(base_url=API_ROOT, assert_all_called=False) as mock:
        mock.get("/autor/999/").respond(status_code=404)
        with pytest.raises(BppNotFound):
            await client.get_json("autor/999/", use_cache=False)


async def test_404_nie_jest_retryowane(client):
    # 404 to trwały brak zasobu — NIE ma sensu retryować (D9a).
    with respx.mock(base_url=API_ROOT, assert_all_called=False) as mock:
        route = mock.get("/autor/999/").respond(status_code=404)
        with pytest.raises(BppNotFound):
            await client.get_json("autor/999/", use_cache=False)
    assert route.call_count == 1


async def test_4xx_nie_jest_retryowane_i_niesie_body(client):
    # 400/422 to błąd żądania (nie sieci) — nie retryujemy, a ciało DRF
    # (wskazówka walidacji) trafia do komunikatu (D9a + D3).
    with respx.mock(base_url=API_ROOT, assert_all_called=False) as mock:
        route = mock.get("/wydawnictwo_ciagle/").respond(
            status_code=400,
            json={"charakter_formalny": ["Wybierz poprawny klucz (PK)."]},
        )
        with pytest.raises(BppError) as exc:
            await client.get_json("wydawnictwo_ciagle/", use_cache=False)
    assert route.call_count == 1
    assert "400" in str(exc.value)
    assert "poprawny klucz" in str(exc.value)


async def test_5xx_wyczerpuje_retry():
    # Trwałe 5xx → po (1 + max_retries) próbach podnosimy BppNetworkError (D9b).
    client = BppClient(Config(base_url=BASE_URL), max_retries=2, backoff_base=0.0)
    try:
        with respx.mock(base_url=API_ROOT, assert_all_called=False) as mock:
            route = mock.get("/jezyk/").respond(status_code=503)
            with pytest.raises(BppNetworkError):
                await client.get_json("jezyk/", use_cache=False)
        assert route.call_count == 3
    finally:
        await client.aclose()


async def test_get_paginated_obcina_w_pol_strony(client):
    # limit=3, strony po 2 → zbierze 4, przytnie do 3; laczna = serwerowy count.
    strona1 = {
        "count": 5,
        "next": f"{API_ROOT}/wydawnictwo_ciagle/?limit=3&offset=2",
        "results": [{"id": 1}, {"id": 2}],
    }
    strona2 = {"count": 5, "next": None, "results": [{"id": 3}, {"id": 4}]}
    with respx.mock(base_url=API_ROOT, assert_all_called=False) as mock:
        route = mock.get("/wydawnictwo_ciagle/")
        route.side_effect = [
            httpx.Response(200, json=strona1),
            httpx.Response(200, json=strona2),
        ]
        zebrane, laczna = await client.get_paginated("wydawnictwo_ciagle/", limit=3)
    assert [p["id"] for p in zebrane] == [1, 2, 3]
    assert laczna == 5
    assert route.call_count == 2


async def test_cache_nie_rosnie_dla_rekordow(client):
    # Rekordy/streszczenia/through NIE są cache'owane, nawet przy use_cache=True
    # (prefiks spoza PREFIKSY_CACHOWALNE). Cache nie puchnie (D9e, W4).
    with respx.mock(base_url=API_ROOT, assert_all_called=False) as mock:
        rekord = mock.get("/wydawnictwo_ciagle/100/").respond(json={"id": 100})
        await client.get_json("wydawnictwo_ciagle/100/")
        await client.get_json("wydawnictwo_ciagle/100/")
    # brak cache → dwa realne żądania
    assert rekord.call_count == 2
    assert client._cache == {}


async def test_cache_rosnie_dla_slownikow(client):
    # Kontrola pozytywna: słownik (whitelista) JEST cache'owany.
    with respx.mock(base_url=API_ROOT, assert_all_called=False) as mock:
        route = mock.get("/jednostka/1/").respond(json={"id": 1})
        await client.get_json("jednostka/1/")
        await client.get_json("jednostka/1/")
    assert route.call_count == 1
    assert len(client._cache) == 1
