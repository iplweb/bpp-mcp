import httpx
import pytest
import respx

from bpp_mcp import auth
from bpp_mcp.client import BppClient, BppError
from bpp_mcp.config import Config

BASE = "https://bpp.example.test"
PING = f"{BASE}/api/v1/uczelnia/1/"


def _cfg(basic=None, transport="stdio"):
    return Config(base_url=BASE, basic_auth=basic, transport=transport)


@pytest.fixture(autouse=True)
def _czysty_bearer():
    auth.set_current_bearer(None)
    yield
    auth.set_current_bearer(None)


@pytest.mark.asyncio
@respx.mock
async def test_bearer_forwardowany():
    auth.set_current_bearer("TESTTOKEN")
    route = respx.get(PING).mock(return_value=httpx.Response(200, json={"ok": 1}))
    async with BppClient(_cfg(transport="http")) as c:
        await c.get_json("uczelnia/1/")
    assert route.calls.last.request.headers["Authorization"] == "Bearer TESTTOKEN"


@pytest.mark.asyncio
@respx.mock
async def test_stdio_bez_bearera_anon():
    route = respx.get(PING).mock(return_value=httpx.Response(200, json={"ok": 1}))
    async with BppClient(_cfg()) as c:
        await c.get_json("uczelnia/1/")
    assert "Authorization" not in route.calls.last.request.headers


@pytest.mark.asyncio
@respx.mock
async def test_stdio_basic_gdy_brak_bearera():
    route = respx.get(PING).mock(return_value=httpx.Response(200, json={"ok": 1}))
    async with BppClient(_cfg(basic="u:p")) as c:
        await c.get_json("uczelnia/1/")
    # Basic base64("u:p") == "dTpw"
    assert route.calls.last.request.headers["Authorization"] == "Basic dTpw"


@pytest.mark.asyncio
@respx.mock
async def test_http_bez_bearera_blad():
    respx.get(PING).mock(return_value=httpx.Response(200, json={"ok": 1}))
    async with BppClient(_cfg(basic="u:p", transport="http")) as c:
        with pytest.raises(BppError):
            await c.get_json("uczelnia/1/")
