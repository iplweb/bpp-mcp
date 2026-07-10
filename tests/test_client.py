import httpx
import pytest
import respx

from bpp_mcp.client import BppClient, BppNotFound
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
