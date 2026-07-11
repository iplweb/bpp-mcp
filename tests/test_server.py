from bpp_mcp.server import mcp


async def test_zarejestrowano_osiem_narzedzi():
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
        "djangoql_schema",
    }


async def test_zarejestrowano_prompt_zloz_zapytanie():
    prompty = await mcp.list_prompts()
    nazwy = {p.name for p in prompty}
    assert "zloz_zapytanie_djangoql" in nazwy
    prompt = next(p for p in prompty if p.name == "zloz_zapytanie_djangoql")
    assert [a.name for a in (prompt.arguments or [])] == ["opis"]
