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


def _przechwyc_url():
    """open_browser, które NIE otwiera nic (udaje host bez przeglądarki),
    tylko zapamiętuje URL — żeby test mógł zbudować z niego wklejkę."""
    zapisany: dict[str, str] = {}

    def _open(url: str) -> bool:
        zapisany["url"] = url
        return False

    return _open, zapisany


def _wklejka(zapisany, *, code="WKLEJONY", state=None, samo_code=False):
    """Callable udające użytkownika wklejającego adres z paska przeglądarki."""

    def _czytaj() -> str:
        q = urllib.parse.parse_qs(urllib.parse.urlparse(zapisany["url"]).query)
        if samo_code:
            return f"  {code}\n"
        st = state if state is not None else q["state"][0]
        return f"{q['redirect_uri'][0]}?code={code}&state={st}\n"

    return _czytaj


def _stub_serwera():
    """Wspólne mocki: DCR, token, whoami + przepuszczenie loopbacku."""
    _meta()
    respx.post(f"{BASE}/o/register/").mock(
        return_value=httpx.Response(201, json={"client_id": "CID"})
    )
    route = respx.post(f"{BASE}/o/token/").mock(
        return_value=httpx.Response(
            200, json={"access_token": "AT", "expires_in": 1800}
        )
    )
    respx.get(f"{BASE}/api/v1/whoami/").mock(
        return_value=httpx.Response(200, json={"username": "x"})
    )
    respx.route(host="127.0.0.1").pass_through()
    return route


@respx.mock
def test_login_wypisuje_url_autoryzacji_tekstem():
    """Na hoście zdalnym/bez GUI przeglądarka może się nie otworzyć — adres
    musi być też wypisany, żeby dało się go otworzyć ręcznie."""
    _stub_serwera()
    komunikaty: list[str] = []
    oauth_client.login(
        BASE, open_browser=_fake_browser(), timeout=10.0, echo=komunikaty.append
    )
    wypisane = "\n".join(komunikaty)
    assert f"{BASE}/o/authorize/" in wypisane
    assert "code_challenge" in wypisane  # pełny URL, nie sam prefiks


@respx.mock
def test_login_przyjmuje_wklejony_url_callbacku():
    """Ścieżka zdalna: przeglądarka działa na innej maszynie niż bpp-mcp, więc
    callback na 127.0.0.1 nigdy nie wraca. Użytkownik wkleja adres z paska."""
    token_route = _stub_serwera()
    _open, zapisany = _przechwyc_url()
    ts = oauth_client.login(
        BASE,
        open_browser=_open,
        czytaj_wklejone=_wklejka(zapisany),
        timeout=10.0,
    )
    assert ts.access_token == "AT"
    body = dict(urllib.parse.parse_qsl(token_route.calls.last.request.content.decode()))
    assert body["code"] == "WKLEJONY"


@respx.mock
def test_login_przyjmuje_sam_wklejony_kod():
    """Część przeglądarek pokazuje tylko kod (albo user kopiuje sam parametr)."""
    token_route = _stub_serwera()
    _open, zapisany = _przechwyc_url()
    oauth_client.login(
        BASE,
        open_browser=_open,
        czytaj_wklejone=_wklejka(zapisany, code="GOLY", samo_code=True),
        timeout=10.0,
    )
    body = dict(urllib.parse.parse_qsl(token_route.calls.last.request.content.decode()))
    assert body["code"] == "GOLY"


@respx.mock
def test_login_wklejony_url_ze_zlym_state_odrzucony():
    """Wklejka nie może być furtką omijającą kontrolę state — gdy state jest
    obecny, MUSI się zgadzać."""
    _stub_serwera()
    _open, zapisany = _przechwyc_url()
    with pytest.raises(ValueError):
        oauth_client.login(
            BASE,
            open_browser=_open,
            czytaj_wklejone=_wklejka(zapisany, state="PODMIENIONY"),
            timeout=10.0,
        )


@respx.mock
def test_login_timeout_bez_callbacku():
    _meta()
    respx.post(f"{BASE}/o/register/").mock(
        return_value=httpx.Response(201, json={"client_id": "CID"})
    )
    with pytest.raises(TimeoutError):
        oauth_client.login(BASE, open_browser=lambda url: True, timeout=0.4)
