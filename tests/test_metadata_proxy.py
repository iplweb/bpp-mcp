from bpp_mcp.oauth_client import _konwencjonalne, authorization_server_metadata


def test_konwencjonalne_zawiera_revoke():
    m = _konwencjonalne("https://bpp.test/")
    assert m.revocation_endpoint == "https://bpp.test/o/revoke_token/"


def test_metadata_issuer_self_endpointy_bpp():
    doc = authorization_server_metadata("https://bpp.test", "http://127.0.0.1:8000")
    # Funkcja wypisuje issuer DOSŁOWNIE — normalizacja należy wyłącznie do
    # AuthSettings w build_mcp, żeby PRM i dokument AS nie mogły się rozjechać
    # (RFC 8414 §3.3: issuer == adres pobrania, porównywany bajt w bajt).
    assert doc["issuer"] == "http://127.0.0.1:8000"
    assert doc["authorization_endpoint"] == "https://bpp.test/o/authorize/"
    assert doc["token_endpoint"] == "https://bpp.test/o/token/"
    assert doc["registration_endpoint"] == "https://bpp.test/o/register/"
    assert doc["revocation_endpoint"] == "https://bpp.test/o/revoke_token/"
    assert doc["code_challenge_methods_supported"] == ["S256"]
    assert doc["token_endpoint_auth_methods_supported"] == ["none"]


def test_metadata_issuer_ze_sciezka_normalizacja():
    # Builder poprawnie odwzorowuje issuer ze ścieżką (AnyHttpUrl NIE dokłada
    # ukośnika). UWAGA: taki issuer to NIE wspierana konfiguracja discovery —
    # klient MCP buduje wtedy URL-e path-inserted i nie trafia w naszą gołą
    # trasę /.well-known/oauth-authorization-server. issuer musi być gołym
    # originem; ten test sprawdza tylko konstrukcję dokumentu, nie osiągalność.
    doc = authorization_server_metadata("https://bpp.test", "https://mcp.example/bpp")
    assert doc["issuer"] == "https://mcp.example/bpp"
