from bpp_mcp.config import Config


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
