from __future__ import annotations

import types

import pytest

from bpp_mcp import auth
from bpp_mcp.server import KontekstApp, _client


class _FakeProvider:
    def __init__(self, token):
        self._token = token

    async def bearer(self):
        return self._token


def _ctx(*, request, provider):
    kctx = KontekstApp(client="SENTINEL", bearer_provider=provider)
    rc = types.SimpleNamespace(request=request, lifespan_context=kctx)
    return types.SimpleNamespace(request_context=rc)


@pytest.mark.asyncio
async def test_stdio_bierze_bearer_z_providera():
    auth.set_current_bearer(None)
    ctx = _ctx(request=None, provider=_FakeProvider("Z_CACHE"))
    assert await _client(ctx) == "SENTINEL"
    assert auth.current_bearer() == "Z_CACHE"
    auth.set_current_bearer(None)


@pytest.mark.asyncio
async def test_request_bearer_wygrywa_z_providerem():
    auth.set_current_bearer(None)
    req = types.SimpleNamespace(headers={"authorization": "Bearer Z_REQ"})
    ctx = _ctx(request=req, provider=_FakeProvider("Z_CACHE"))
    assert await _client(ctx) == "SENTINEL"
    assert auth.current_bearer() == "Z_REQ"  # http/request wygrywa
    auth.set_current_bearer(None)


@pytest.mark.asyncio
async def test_brak_providera_i_requestu_none():
    auth.set_current_bearer(None)
    ctx = _ctx(request=None, provider=None)
    assert await _client(ctx) == "SENTINEL"
    assert auth.current_bearer() is None
    auth.set_current_bearer(None)
