"""Każde narzędzie bpp-mcp ogłasza się klientowi jako TYLKO DO ODCZYTU.

Klienci MCP traktują narzędzie bez ``readOnlyHint: true`` jak zapisujące —
ChatGPT (developer mode) każe wtedy użytkownikowi potwierdzać KAŻDE wywołanie.
Żadne narzędzie bpp-mcp niczego nie zmienia, więc wszystkie 11 niesie
adnotacje z :data:`bpp_mcp.server.ADNOTACJE_TYLKO_ODCZYT`.

Sprawdzamy po protokole (``tools/list`` przez klienta w procesie), a nie przez
``_tool_manager``: liczy się to, co zobaczy klient. Drugi test pilnuje, że
adnotacje docierają też do hosta, który woła :func:`register_tools` na własnym
``MCPServer`` z podmienionym ``serwer.tool`` — tak robi BPP
(``mcp_server.aplikacja._z_raportowaniem``). Adnotacje dopięte inną drogą niż
argument ``mcp.tool(...)`` mogłyby do takiego hosta nie trafić.
"""

from __future__ import annotations

import functools

from mcp import Client
from mcp.server.mcpserver import MCPServer

from bpp_mcp.server import register_tools

# Tak mają wyglądać adnotacje na drucie (camelCase, bez pól nieustawionych).
OCZEKIWANE_NA_DRUCIE = {
    "readOnlyHint": True,
    "idempotentHint": True,
    "openWorldHint": False,
}


async def _narzedzia_po_protokole(mcp: MCPServer):
    async with Client(mcp) as client:
        wynik = await client.list_tools()
    return wynik.tools


def _sprawdz_adnotacje(narzedzia) -> None:
    assert len(narzedzia) == 11
    bez_adnotacji = [n.name for n in narzedzia if n.annotations is None]
    assert not bez_adnotacji, f"narzędzia bez adnotacji: {bez_adnotacji}"
    for narzedzie in narzedzia:
        assert narzedzie.annotations.read_only_hint is True, narzedzie.name
        assert (
            narzedzie.annotations.model_dump(by_alias=True, exclude_none=True)
            == OCZEKIWANE_NA_DRUCIE
        ), narzedzie.name


async def test_kazde_narzedzie_jest_tylko_do_odczytu():
    mcp = MCPServer("test-adnotacji")
    register_tools(mcp)

    _sprawdz_adnotacje(await _narzedzia_po_protokole(mcp))


async def test_adnotacje_docieraja_do_hosta_z_owinietym_tool():
    """Host podmienia ``serwer.tool`` na wrapper przekazujący ``*args,
    **kwargs`` do oryginału i owijający funkcję narzędzia — wzorem BPP."""
    mcp = MCPServer("test-hosta")
    oryginalny = mcp.tool
    owiniete: list[str] = []

    def tool(*args, **kwargs):
        dekorator = oryginalny(*args, **kwargs)

        def opakuj(fn):
            @functools.wraps(fn)
            async def wrapper(*a, **kw):
                return await fn(*a, **kw)

            owiniete.append(fn.__name__)
            return dekorator(wrapper)

        return opakuj

    mcp.tool = tool
    register_tools(mcp)

    # Kontrola, że test naprawdę przeszedł przez wrapper hosta.
    assert len(owiniete) == 11
    _sprawdz_adnotacje(await _narzedzia_po_protokole(mcp))
