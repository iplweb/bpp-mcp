"""Testy parsera schematu DjangoQL (:mod:`bpp_mcp.schemat`).

Parser jest czysty (bez I/O i bez sieci), więc testy jednostkowe jadą na
sztucznym mini-schemacie trzymanym w stringu — nie na zasobach pakietu.
Osobna sekcja na końcu to test kontraktu formatu: pilnuje, że zbundlowane
pliki z głównego BPP nadal parsują się tak, jak zakłada `schemat.py`.
"""

from importlib import resources

import pytest

from bpp_mcp import schemat as sch

# Sztuczny mini-schemat: ma wszystkie elementy prawdziwego pliku (preambuła
# z ``start model:``, kilka sekcji modeli, blok ``dictionaries`` na końcu),
# ale mieści się na ekranie.
MINI = """\
# BPP 202607.1
# Model: bpp.Rekord

# DjangoQL schema
# Query: <field> <op> <value>

start model: bpp.rekord

bpp.rekord:
  autorzy      -> bpp.autorzy?
  tytul        str

bpp.autorzy:
  autor        -> bpp.autor

bpp.zrodlo:
  nazwa        str

dictionaries (shared relation values, referenced above):
  bpp.jezyk
    nazwa: "polski", "angielski"
"""

BEZ_START_MODEL = """\
# BPP 202607.1

bpp.rekord:
  tytul        str

dictionaries (shared relation values, referenced above):
  bpp.jezyk
    nazwa: "polski"
"""

BEZ_SEKCJI_KORZENIA = """\
# BPP 202607.1

start model: bpp.nie_ma_takiego

bpp.rekord:
  tytul        str

dictionaries (shared relation values, referenced above):
  bpp.jezyk
    nazwa: "polski"
"""

PLIKI_ZBUNDLOWANE = (
    "rekord_djangoql_schema.compact.txt",
    "autor_djangoql_schema.compact.txt",
    "autorzy_djangoql_schema.compact.txt",
)


def _tekst_zasobu(nazwa: str) -> str:
    return (
        resources.files("bpp_mcp").joinpath("data", nazwa).read_text(encoding="utf-8")
    )


# --- podziel() ------------------------------------------------------------


def test_podziel_granice_sekcji():
    s = sch.podziel(MINI)
    # Kolejność z pliku, wszystkie trzy modele, bez ``dictionaries``.
    assert list(s.sekcje) == ["bpp.rekord", "bpp.autorzy", "bpp.zrodlo"]
    assert s.sekcje["bpp.rekord"].startswith("bpp.rekord:")
    assert "tytul" in s.sekcje["bpp.rekord"]
    # Blok kończy się na następnym nagłówku — nie wchłania sąsiada.
    assert "bpp.autorzy:" not in s.sekcje["bpp.rekord"]
    assert "autor " not in s.sekcje["bpp.rekord"]


def test_podziel_ostatnia_sekcja_konczy_sie_przed_dictionaries():
    s = sch.podziel(MINI)
    ostatnia = s.sekcje["bpp.zrodlo"]
    assert ostatnia.startswith("bpp.zrodlo:")
    assert "nazwa" in ostatnia
    assert "dictionaries" not in ostatnia
    assert "polski" not in ostatnia


def test_podziel_preambula_konczy_sie_na_pierwszym_naglowku():
    s = sch.podziel(MINI)
    assert s.preambula.startswith("# BPP")
    assert "DjangoQL schema" in s.preambula
    assert "start model: bpp.rekord" in s.preambula
    assert "bpp.rekord:" not in s.preambula


def test_podziel_korzen_z_start_model():
    assert sch.podziel(MINI).korzen == "bpp.rekord"


def test_podziel_dictionaries_nie_trafia_do_sekcji():
    s = sch.podziel(MINI)
    assert "dictionaries" not in s.sekcje
    assert s.slowniki.startswith("dictionaries")
    assert "polski" in s.slowniki


def test_podziel_bloki_bez_koncowych_pustych_linii():
    s = sch.podziel(MINI)
    for blok in (s.preambula, s.slowniki, *s.sekcje.values()):
        assert blok == blok.rstrip()


def test_podziel_bez_start_model_wyjatek():
    with pytest.raises(ValueError) as exc:
        sch.podziel(BEZ_START_MODEL)
    assert "start model" in str(exc.value)


def test_podziel_bez_sekcji_korzenia_wyjatek():
    with pytest.raises(ValueError) as exc:
        sch.podziel(BEZ_SEKCJI_KORZENIA)
    assert "bpp.nie_ma_takiego" in str(exc.value)


# --- rdzen() --------------------------------------------------------------


def test_rdzen_sklada_preambule_korzen_slowniki_w_kolejnosci():
    s = sch.podziel(MINI)
    wynik = sch.rdzen(s)
    assert wynik == "\n\n".join([s.preambula, s.sekcje[s.korzen], s.slowniki]) + "\n"
    assert wynik.startswith("# BPP")
    assert wynik.endswith("\n")
    assert wynik.index("start model:") < wynik.index("bpp.rekord:")
    assert wynik.index("bpp.rekord:") < wynik.index("dictionaries")
    # Sekcje spoza rdzenia nie wchodzą.
    assert "bpp.zrodlo:" not in wynik
    assert "bpp.autorzy:" not in wynik


def test_rdzen_bez_sekcji_korzenia_wyjatek():
    s = sch.Schemat(
        preambula="# BPP",
        korzen="bpp.rekord",
        sekcje={"bpp.zrodlo": "bpp.zrodlo:\n  nazwa str"},
        slowniki="dictionaries:\n  x",
    )
    with pytest.raises(ValueError) as exc:
        sch.rdzen(s)
    assert "bpp.rekord" in str(exc.value)


def test_rdzen_pusty_wynik_wyjatek():
    s = sch.Schemat(
        preambula="",
        korzen="bpp.rekord",
        sekcje={"bpp.rekord": ""},
        slowniki="",
    )
    with pytest.raises(ValueError):
        sch.rdzen(s)


# --- wytnij() -------------------------------------------------------------


def test_wytnij_kolejnosc_z_pliku_niezalezna_od_argumentow():
    s = sch.podziel(MINI)
    a = sch.wytnij(s, ["bpp.zrodlo", "bpp.autorzy"])
    b = sch.wytnij(s, ["bpp.autorzy", "bpp.zrodlo"])
    assert a == b
    assert a.index("bpp.autorzy:") < a.index("bpp.zrodlo:")
    assert a == "\n\n".join([s.sekcje["bpp.autorzy"], s.sekcje["bpp.zrodlo"]]) + "\n"
    # Rdzenia tu nie ma.
    assert "# BPP" not in a
    assert "dictionaries" not in a


def test_wytnij_deduplikuje():
    s = sch.podziel(MINI)
    jeden = sch.wytnij(s, ["bpp.zrodlo"])
    assert sch.wytnij(s, ["bpp.zrodlo", "bpp.zrodlo", "bpp.zrodlo"]) == jeden
    assert jeden.count("bpp.zrodlo:") == 1


def test_wytnij_nieznana_nazwa_wyjatek_z_sugestia():
    s = sch.podziel(MINI)
    with pytest.raises(ValueError) as exc:
        sch.wytnij(s, ["bpp.zrodo"])
    komunikat = str(exc.value)
    assert "bpp.zrodo" in komunikat
    # difflib podpowiada najbliższe dopasowanie.
    assert "bpp.zrodlo" in komunikat


def test_wytnij_wiele_nieznanych_wymienia_wszystkie():
    s = sch.podziel(MINI)
    with pytest.raises(ValueError) as exc:
        sch.wytnij(s, ["bpp.aaa", "bpp.zrodlo", "bpp.bbb"])
    komunikat = str(exc.value)
    assert "bpp.aaa" in komunikat
    assert "bpp.bbb" in komunikat


def test_wytnij_nazwa_korzenia_wyjatek_o_rdzeniu():
    s = sch.podziel(MINI)
    with pytest.raises(ValueError) as exc:
        sch.wytnij(s, ["bpp.rekord"])
    komunikat = str(exc.value)
    assert "bpp.rekord" in komunikat
    assert "rdzeni" in komunikat  # „…jest już w rdzeniu”
    assert "sekcje" in komunikat


def test_wytnij_dictionaries_wyjatek_o_rdzeniu():
    s = sch.podziel(MINI)
    with pytest.raises(ValueError) as exc:
        sch.wytnij(s, ["dictionaries"])
    assert "dictionaries" in str(exc.value)
    assert "rdzeni" in str(exc.value)


def test_wytnij_bez_nazw_wyjatek():
    # Pusty wynik byłby cichą awarią — warstwa narzędzia dla ``sekcje=[]``
    # ma wołać ``rdzen()``, nie ``wytnij()``.
    s = sch.podziel(MINI)
    with pytest.raises(ValueError):
        sch.wytnij(s, [])


# --- kontrakt formatu (prawdziwe zbundlowane pliki) -----------------------


@pytest.mark.parametrize("nazwa_pliku", PLIKI_ZBUNDLOWANE)
def test_kontrakt_formatu_zbundlowanych_plikow(nazwa_pliku):
    tekst = _tekst_zasobu(nazwa_pliku)
    s = sch.podziel(tekst)

    assert len(s.sekcje) >= 50, nazwa_pliku
    assert "start model:" in s.preambula, nazwa_pliku
    assert s.slowniki.startswith("dictionaries"), nazwa_pliku
    assert s.slowniki.strip(), nazwa_pliku
    assert s.korzen in s.sekcje, nazwa_pliku
    assert s.sekcje[s.korzen].strip(), nazwa_pliku

    rdzen = sch.rdzen(s)
    assert rdzen.startswith("# BPP"), nazwa_pliku
    assert len(rdzen) < 0.4 * len(tekst), nazwa_pliku
