import httpx

from bpp_mcp.oauth_client import AuthMode, probe_instance


def _client(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_passthrough_gdy_poprawne_metadane():
    def h(_req):
        return httpx.Response(
            200, json={"authorization_endpoint": "a", "token_endpoint": "t"}
        )

    assert probe_instance("https://bpp.test", client=_client(h)) is AuthMode.PASSTHROUGH


def test_proxy_gdy_403():
    def h(_req):
        return httpx.Response(403, text="<html>forbidden</html>")

    assert probe_instance("https://bpp.test", client=_client(h)) is AuthMode.PROXY


def test_proxy_gdy_html_200():
    def h(_req):
        return httpx.Response(200, text="<html>nie json</html>")

    assert probe_instance("https://bpp.test", client=_client(h)) is AuthMode.PROXY


def test_proxy_gdy_brak_wymaganych_pol():
    def h(_req):
        return httpx.Response(200, json={"issuer": "x"})

    assert probe_instance("https://bpp.test", client=_client(h)) is AuthMode.PROXY


def test_proxy_gdy_timeout():
    def h(_req):
        raise httpx.ConnectTimeout("wolno")

    assert probe_instance("https://bpp.test", client=_client(h)) is AuthMode.PROXY


def test_proxy_gdy_5xx():
    def h(_req):
        return httpx.Response(502, text="bad gateway")

    assert probe_instance("https://bpp.test", client=_client(h)) is AuthMode.PROXY
