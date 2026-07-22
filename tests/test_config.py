import pytest

from bpp_mcp.config import BrakKonfiguracji, Config


def test_from_env_bez_hosta_podnosi_czytelny_blad(monkeypatch):
    """Brak ``BPP_BASE_URL`` musi być głośny.

    Serwer jest wielo-instancyjny — cichy fallback na zaszytą uczelnię oznaczał
    kiedyś, że użytkownik dostaje bibliografię CUDZEJ instytucji, przekonany,
    że pyta swoją. Lepszy głośny błąd niż poprawnie wyglądające, cudze dane.
    """
    monkeypatch.delenv("BPP_BASE_URL", raising=False)
    with pytest.raises(BrakKonfiguracji) as ei:
        Config.from_env()
    komunikat = str(ei.value)
    assert "BPP_BASE_URL" in komunikat
    assert "https://" in komunikat  # komunikat pokazuje, jak to ustawić


def test_from_env_pusty_host_traktowany_jak_brak(monkeypatch):
    monkeypatch.setenv("BPP_BASE_URL", "   ")
    with pytest.raises(BrakKonfiguracji):
        Config.from_env()


def test_from_env_czyta_host_ze_zmiennej(monkeypatch):
    monkeypatch.setenv("BPP_BASE_URL", "https://publikacje.up.lublin.pl/")
    assert Config.from_env().base_url == "https://publikacje.up.lublin.pl/"


def test_brak_zaszytej_uczelni_w_module():
    """Żadna konkretna instancja nie może być wpisana w kod na sztywno."""
    import bpp_mcp.config as modul

    assert not hasattr(modul, "DEFAULT_BASE_URL")


def test_from_env_transport_defaults(monkeypatch):
    for k in (
        "BPP_MCP_TRANSPORT",
        "BPP_MCP_HTTP_HOST",
        "BPP_MCP_HTTP_PORT",
        "BPP_MCP_RESOURCE_URL",
    ):
        monkeypatch.delenv(k, raising=False)
    cfg = Config.from_env()
    assert cfg.transport == "stdio"
    assert cfg.http_host == "127.0.0.1"
    assert cfg.http_port == 8000
    assert cfg.effective_resource_url == "http://127.0.0.1:8000/mcp"


def test_from_env_transport_http(monkeypatch):
    monkeypatch.setenv("BPP_MCP_TRANSPORT", "HTTP")
    monkeypatch.setenv("BPP_MCP_HTTP_PORT", "9123")
    monkeypatch.delenv("BPP_MCP_RESOURCE_URL", raising=False)
    cfg = Config.from_env()
    assert cfg.transport == "http"
    assert cfg.http_port == 9123
    assert cfg.effective_resource_url == "http://127.0.0.1:9123/mcp"


def test_resource_url_override(monkeypatch):
    monkeypatch.setenv("BPP_MCP_RESOURCE_URL", "http://127.0.0.1:9000/mcp")
    cfg = Config.from_env()
    assert cfg.effective_resource_url == "http://127.0.0.1:9000/mcp"
