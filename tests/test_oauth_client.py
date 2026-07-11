from __future__ import annotations

import base64
import hashlib

import httpx
import pytest
import respx

from bpp_mcp import oauth_client
from bpp_mcp.oauth_client import Metadata, RefreshFailed
from bpp_mcp.token_store import TokenSet

BASE = "https://bpp.test"
META_URL = f"{BASE}/.well-known/oauth-authorization-server"


def _meta_body():
    return {
        "issuer": BASE,
        "authorization_endpoint": f"{BASE}/o/authorize/",
        "token_endpoint": f"{BASE}/o/token/",
        "registration_endpoint": f"{BASE}/o/register/",
        "code_challenge_methods_supported": ["S256"],
    }


@respx.mock
def test_discover():
    respx.get(META_URL).mock(return_value=httpx.Response(200, json=_meta_body()))
    meta = oauth_client.discover(BASE)
    assert meta.authorization_endpoint == f"{BASE}/o/authorize/"
    assert meta.token_endpoint == f"{BASE}/o/token/"
    assert meta.registration_endpoint == f"{BASE}/o/register/"


@respx.mock
def test_register_client():
    meta = Metadata(f"{BASE}/o/authorize/", f"{BASE}/o/token/", f"{BASE}/o/register/")
    route = respx.post(f"{BASE}/o/register/").mock(
        return_value=httpx.Response(201, json={"client_id": "CID123"})
    )
    cid = oauth_client.register_client(meta, "http://127.0.0.1:5000/callback")
    assert cid == "CID123"
    assert b"127.0.0.1:5000/callback" in route.calls.last.request.content


@respx.mock
def test_register_client_429_dolacza_tresc():
    meta = Metadata(f"{BASE}/o/authorize/", f"{BASE}/o/token/", f"{BASE}/o/register/")
    respx.post(f"{BASE}/o/register/").mock(
        return_value=httpx.Response(429, json={"error": "rate_limited"})
    )
    with pytest.raises(RuntimeError) as ei:
        oauth_client.register_client(meta, "http://127.0.0.1:5000/callback")
    assert "429" in str(ei.value)
    assert "rate_limited" in str(ei.value)


def test_register_client_bez_endpointu():
    meta = Metadata(f"{BASE}/o/authorize/", f"{BASE}/o/token/", None)
    with pytest.raises(RuntimeError):
        oauth_client.register_client(meta, "http://127.0.0.1:5000/callback")


def test_pkce_challenge_is_s256_of_verifier():
    verifier, challenge = oauth_client._pkce()
    oczek = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest())
        .rstrip(b"=")
        .decode("ascii")
    )
    assert challenge == oczek


@respx.mock
def test_refresh_rotuje_i_zwraca_nowy_tokenset():
    ts = TokenSet(
        base_url=BASE,
        access_token="STARY",
        refresh_token="RT_STARY",
        expires_at=0.0,
        token_endpoint=f"{BASE}/o/token/",
        username="k",
        client_id="CID",
    )
    respx.post(f"{BASE}/o/token/").mock(
        return_value=httpx.Response(
            200,
            json={
                "access_token": "NOWY",
                "refresh_token": "RT_NOWY",
                "expires_in": 1800,
            },
        )
    )
    new = oauth_client.refresh(ts)
    assert new.access_token == "NOWY"
    assert new.refresh_token == "RT_NOWY"
    assert new.token_endpoint == ts.token_endpoint
    assert new.client_id == "CID"
    assert new.expires_at > ts.expires_at


@respx.mock
def test_refresh_bez_rotacji_zachowuje_stary_rt():
    ts = TokenSet(
        base_url=BASE,
        access_token="A",
        refresh_token="RT_STARY",
        expires_at=0.0,
        token_endpoint=f"{BASE}/o/token/",
        client_id="CID",
    )
    respx.post(f"{BASE}/o/token/").mock(
        return_value=httpx.Response(
            200, json={"access_token": "NOWY", "expires_in": 1800}
        )
    )
    assert oauth_client.refresh(ts).refresh_token == "RT_STARY"


@respx.mock
def test_refresh_odrzucony_podnosi_refreshfailed():
    ts = TokenSet(
        base_url=BASE,
        access_token="A",
        refresh_token="RT",
        expires_at=0.0,
        token_endpoint=f"{BASE}/o/token/",
        client_id="CID",
    )
    respx.post(f"{BASE}/o/token/").mock(
        return_value=httpx.Response(400, json={"error": "invalid_grant"})
    )
    with pytest.raises(RefreshFailed):
        oauth_client.refresh(ts)


def test_refresh_bez_refresh_tokenu_podnosi():
    ts = TokenSet(
        base_url=BASE,
        access_token="A",
        refresh_token=None,
        expires_at=0.0,
        token_endpoint=f"{BASE}/o/token/",
        client_id="CID",
    )
    with pytest.raises(RefreshFailed):
        oauth_client.refresh(ts)


def test_refresh_bez_client_id_podnosi():
    ts = TokenSet(
        base_url=BASE,
        access_token="A",
        refresh_token="RT",
        expires_at=0.0,
        token_endpoint=f"{BASE}/o/token/",
        client_id=None,
    )
    with pytest.raises(RefreshFailed):
        oauth_client.refresh(ts)


@respx.mock
def test_whoami_zwraca_username_lub_none():
    respx.get(f"{BASE}/api/v1/whoami/").mock(
        return_value=httpx.Response(200, json={"id": 1, "username": "nowak"})
    )
    assert oauth_client._whoami(BASE, "AT") == "nowak"


@respx.mock
def test_whoami_nie200_none():
    respx.get(f"{BASE}/api/v1/whoami/").mock(return_value=httpx.Response(500))
    assert oauth_client._whoami(BASE, "AT") is None


@respx.mock
def test_whoami_siec_none():
    respx.get(f"{BASE}/api/v1/whoami/").mock(side_effect=httpx.ConnectError("x"))
    assert oauth_client._whoami(BASE, "AT") is None
