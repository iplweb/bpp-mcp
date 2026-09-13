"""Błąd domenowy :class:`~bpp_mcp.client.BppError` musi dotrzeć do MODELU.

``BppError`` to czytelny komunikat dla agenta (401 anonima, 404 „niewidoczna
lub nie istnieje", zły argument, budżet czasu) — cały sens tego typu polega na
tym, że model przeczyta treść i poprawi wywołanie.

W ``mcp`` 2.0.0 każdy wyjątek z narzędzia był owijany w ``ToolError`` razem
z treścią. Od ``mcp`` 2.1 „przewidziane" są wyłącznie ``ToolError`` i
``ResourceError``; każdy inny wyjątek staje się
``UnexpectedToolError("Error executing tool <nazwa>")`` — treść jest UKRYTA
przed modelem, a serwer loguje pełny traceback jak przy awarii. Stąd
``BppError`` dziedziczy po ``ToolError``.

Uwaga: ``UnexpectedToolError`` sam dziedziczy po ``ToolError``, więc
``pytest.raises(ToolError)`` NIE odróżnia obu przypadków — testy sprawdzają
typ wprost i treść wyniku po protokole.
"""

from __future__ import annotations

import logging

import pytest
from mcp import Client
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError, UnexpectedToolError

from bpp_mcp.client import BppError, BppNetworkError, BppNotFound
from bpp_mcp.server import register_tools

KOMUNIKAT = "Jednostka niewidoczna lub nie istnieje (sprawdź ID lub slug)."


def _serwer_z_bledem(typ: type[BppError]) -> MCPServer:
    mcp = MCPServer("test-bledow")

    @mcp.tool()
    async def psuje_sie() -> str:
        """Narzędzie, które zawsze podnosi błąd domenowy."""
        raise typ(KOMUNIKAT, status_code=404)

    return mcp


TYPY = [BppError, BppNotFound, BppNetworkError]


@pytest.mark.parametrize("typ", TYPY, ids=lambda t: t.__name__)
async def test_bpperror_jest_przewidzianym_bledem_narzedzia(typ):
    """Na poziomie serwera: ``call_tool`` podnosi ``ToolError`` z treścią —
    nie ``UnexpectedToolError`` z generycznym „Error executing tool"."""
    mcp = _serwer_z_bledem(typ)

    with pytest.raises(ToolError) as ei:
        await mcp.call_tool("psuje_sie", {})

    assert not isinstance(ei.value, UnexpectedToolError)
    assert KOMUNIKAT in str(ei.value)


@pytest.mark.parametrize("typ", TYPY, ids=lambda t: t.__name__)
async def test_tresc_bpperror_dociera_do_modelu_po_protokole(typ, caplog):
    """Po protokole: wynik ma ``is_error`` i treść komunikatu, a serwer NIE
    loguje tracebacku jak przy awarii."""
    mcp = _serwer_z_bledem(typ)

    with caplog.at_level(logging.INFO):
        async with Client(mcp) as client:
            wynik = await client.call_tool("psuje_sie", {})

    assert wynik.is_error
    tekst = " ".join(c.text for c in wynik.content if c.type == "text")
    assert KOMUNIKAT in tekst
    assert not [
        r for r in caplog.records if r.levelno >= logging.ERROR or r.exc_info
    ], "BppError zalogowany jak nieprzewidziana awaria"


async def test_prawdziwe_narzedzie_oddaje_tresc_bledu():
    """To samo dla narzędzia rejestrowanego przez :func:`register_tools`
    (``djangoql_schema`` nie sięga do sieci ani do lifespanu)."""
    mcp = MCPServer("test-hosta")
    register_tools(mcp)

    async with Client(mcp) as client:
        wynik = await client.call_tool("djangoql_schema", {"model": "bzdura"})

    assert wynik.is_error
    tekst = " ".join(c.text for c in wynik.content if c.type == "text")
    assert "Nieznany model schematu 'bzdura'" in tekst
