"""Testy bezpiecznika offline z ``conftest._bez_sieci``.

Sam bezpiecznik jest odpowiedzią na to, że po porcie na SDK 2.0 respx przestał
wystarczać jako gwarancja: SDK chodzi po ``httpx2``, którego respx nie
przechwytuje. Bez tych dwóch testów blokada mogłaby przestać działać (np. przy
zmianie sposobu patchowania) i nikt by nie zauważył — a wtedy „testy są
offline" z ``docs/rozwoj.md`` stałoby się obietnicą bez pokrycia.
"""

from __future__ import annotations

import socket

import pytest


def test_polaczenie_na_zewnatrz_jest_zablokowane():
    with pytest.raises(RuntimeError, match="Test próbował połączyć się z siecią"):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(1)
            s.connect(("example.invalid", 80))


def test_loopback_pozostaje_dozwolony():
    """Logowanie OAuth stawia serwer loopback (RFC 8252) — blokada nie może go
    zabić. Łączymy się z realnie nasłuchującym gniazdem na 127.0.0.1."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as serwer:
        serwer.bind(("127.0.0.1", 0))
        serwer.listen(1)
        port = serwer.getsockname()[1]

        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as klient:
            klient.settimeout(1)
            klient.connect(("127.0.0.1", port))  # nie może rzucić
            assert klient.getpeername()[0] == "127.0.0.1"
