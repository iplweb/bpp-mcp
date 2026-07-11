from __future__ import annotations

import threading
import urllib.parse

import httpx
import pytest
import respx

from bpp_mcp import oauth_client

BASE = "https://bpp.test"


def _meta():
    respx.get(f"{BASE}/.well-known/oauth-authorization-server").mock(
        return_value=httpx.Response(
            200,
            json={
                "authorization_endpoint": f"{BASE}/o/authorize/",
                "token_endpoint": f"{BASE}/o/token/",
                "registration_endpoint": f"{BASE}/o/register/",
            },
        )
    )


def _fake_browser(*, code="KOD", tamper_state=False):
    """Callable udające webbrowser.open: parsuje authorize URL i w osobnym
    wątku uderza w loopback callback z code+state."""

    def _open(url: str) -> bool:
        q = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
        redirect = q["redirect_uri"][0]
        state = "ZLE" if tamper_state else q["state"][0]

        def _hit():
            httpx.get(f"{redirect}?code={code}&state={state}")

        threading.Thread(target=_hit, daemon=True).start()
        return True

    return _open


@respx.mock
def test_login_pelny_flow():
    _meta()
    respx.post(f"{BASE}/o/register/").mock(
        return_value=httpx.Response(201, json={"client_id": "CID"})
    )
    token_route = respx.post(f"{BASE}/o/token/").mock(
        return_value=httpx.Response(
            200,
            json={"access_token": "AT", "refresh_token": "RT", "expires_in": 1800},
        )
    )
    respx.get(f"{BASE}/api/v1/whoami/").mock(
        return_value=httpx.Response(200, json={"id": 3, "username": "dabrowski"})
    )
    respx.route(host="127.0.0.1").pass_through()

    ts = oauth_client.login(BASE, open_browser=_fake_browser(), timeout=10.0)
    assert ts.access_token == "AT"
    assert ts.refresh_token == "RT"
    assert ts.username == "dabrowski"
    assert ts.client_id == "CID"
    assert ts.token_endpoint == f"{BASE}/o/token/"

    body = dict(urllib.parse.parse_qsl(token_route.calls.last.request.content.decode()))
    assert body["grant_type"] == "authorization_code"
    assert body["code"] == "KOD"
    assert body["code_verifier"]  # PKCE verifier, nie challenge
    assert body["redirect_uri"].startswith("http://127.0.0.1:")


@respx.mock
def test_login_existing_client_id_pomija_dcr():
    _meta()
    reg = respx.post(f"{BASE}/o/register/")
    respx.post(f"{BASE}/o/token/").mock(
        return_value=httpx.Response(
            200, json={"access_token": "AT", "expires_in": 1800}
        )
    )
    respx.get(f"{BASE}/api/v1/whoami/").mock(
        return_value=httpx.Response(200, json={"username": "x"})
    )
    respx.route(host="127.0.0.1").pass_through()

    ts = oauth_client.login(
        BASE, existing_client_id="CID", open_browser=_fake_browser(), timeout=10.0
    )
    assert ts.client_id == "CID"
    assert reg.call_count == 0


@respx.mock
def test_login_zly_state_odrzucony():
    _meta()
    respx.post(f"{BASE}/o/register/").mock(
        return_value=httpx.Response(201, json={"client_id": "CID"})
    )
    respx.route(host="127.0.0.1").pass_through()
    with pytest.raises(ValueError):
        oauth_client.login(
            BASE, open_browser=_fake_browser(tamper_state=True), timeout=10.0
        )


@respx.mock
def test_login_timeout_bez_callbacku():
    _meta()
    respx.post(f"{BASE}/o/register/").mock(
        return_value=httpx.Response(201, json={"client_id": "CID"})
    )
    with pytest.raises(TimeoutError):
        oauth_client.login(BASE, open_browser=lambda url: True, timeout=0.4)
