from bpp_mcp.server import mcp


async def test_zarejestrowano_siedem_narzedzi():
    narzedzia = await mcp.list_tools()
    nazwy = {n.name for n in narzedzia}
    assert nazwy == {
        "szukaj_publikacji",
        "szukaj_autora",
        "publikacje_autora",
        "publikacje_jednostki",
        "pobierz_rekord",
        "lista_publikacji",
        "slownik",
    }
