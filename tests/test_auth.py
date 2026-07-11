import httpx
import pytest
import respx

from bpp_mcp.auth import (
    WhoamiTokenVerifier,
    WhoamiUnavailable,
    bearer_from_request,
    current_bearer,
    set_current_bearer,
)

BASE = "https://bpp.example.test"
WHOAMI = f"{BASE}/api/v1/whoami/"


@pytest.mark.asyncio
@respx.mock
async def test_valid_token():
    respx.get(WHOAMI).mock(return_value=httpx.Response(
        200, json={"id": 7, "username": "kowalski"}))
    tok = await WhoamiTokenVerifier(BASE).verify_token("OPAQUE")
    assert tok is not None
    assert tok.token == "OPAQUE"
    assert tok.scopes == ["read"]
    assert tok.subject == "7"


@pytest.mark.asyncio
@respx.mock
async def test_invalid_token_none():
    respx.get(WHOAMI).mock(return_value=httpx.Response(401))
    assert await WhoamiTokenVerifier(BASE).verify_token("ZLY") is None


@pytest.mark.asyncio
@respx.mock
async def test_5xx_unavailable():
    respx.get(WHOAMI).mock(return_value=httpx.Response(503))
    with pytest.raises(WhoamiUnavailable):
        await WhoamiTokenVerifier(BASE).verify_token("OPAQUE")


@pytest.mark.asyncio
@respx.mock
async def test_siec_unavailable():
    respx.get(WHOAMI).mock(side_effect=httpx.ConnectError("down"))
    with pytest.raises(WhoamiUnavailable):
        await WhoamiTokenVerifier(BASE).verify_token("OPAQUE")


@pytest.mark.asyncio
@respx.mock
async def test_niejson_unavailable():
    respx.get(WHOAMI).mock(return_value=httpx.Response(200, text="nie-json"))
    with pytest.raises(WhoamiUnavailable):
        await WhoamiTokenVerifier(BASE).verify_token("OPAQUE")


@pytest.mark.asyncio
@respx.mock
async def test_cache_hit_w_ttl():
    route = respx.get(WHOAMI).mock(return_value=httpx.Response(
        200, json={"id": 1, "username": "a"}))
    v = WhoamiTokenVerifier(BASE, ttl=60.0)
    await v.verify_token("T")
    await v.verify_token("T")
    assert route.call_count == 1


@pytest.mark.asyncio
@respx.mock
async def test_ttl_0_reweryfikuje():
    route = respx.get(WHOAMI).mock(return_value=httpx.Response(
        200, json={"id": 1, "username": "a"}))
    v = WhoamiTokenVerifier(BASE, ttl=0.0)
    await v.verify_token("T")
    await v.verify_token("T")
    assert route.call_count == 2


def test_bearer_from_request_i_contextvar():
    class Req:
        headers = {"authorization": "Bearer ABC"}
    assert bearer_from_request(Req()) == "ABC"
    assert bearer_from_request(None) is None
    set_current_bearer("XYZ")
    assert current_bearer() == "XYZ"
    set_current_bearer(None)
    assert current_bearer() is None
