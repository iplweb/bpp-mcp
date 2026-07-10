"""Asynchroniczny klient HTTP dla API BPP.

Cechy (wg specu Fazy 2):

* jeden współdzielony ``httpx.AsyncClient`` (zakładany w lifespanie serwera),
* ``timeout = Timeout(10.0, connect=5.0)``,
* nagłówek ``Accept: application/json`` (NIE ``?format=json``),
* retry×2 z narastającym backoffem na błędy sieciowe / 5xx (GET jest
  idempotentny),
* semafor współbieżności (domyślnie 8) — ogranicza równoległe rozwijanie
  hyperlinków w :func:`bpp_mcp.tools.pobierz_rekord`,
* procesowy cache ``URL → JSON`` dla powtarzalnych URL-i (jednostki, słowniki),
* auto-follow paginacji ``LimitOffset`` do zadanego ``limit``,
* mapowanie 404 na czytelny :class:`BppNotFound` zamiast tracebacku.

Żadnego bare ``except`` — łapiemy wąskie typy httpx i re-raise'ujemy sensowny
błąd domenowy.
"""

from __future__ import annotations

import asyncio
from typing import Any

import httpx


class BppError(Exception):
    """Bazowy, czytelny błąd domenowy zwracany narzędziom MCP."""


class BppNotFound(BppError):
    """Zasób zwrócił 404 (rekord ukryty, niewidoczny lub nieistniejący)."""


class BppNetworkError(BppError):
    """Trwały błąd sieci / 5xx po wyczerpaniu prób."""


class BppClient:
    """Cienka, kuratorowana warstwa nad ``httpx.AsyncClient``."""

    def __init__(
        self,
        config,
        *,
        concurrency: int = 8,
        max_retries: int = 2,
        backoff_base: float = 0.5,
    ) -> None:
        self._api_root = config.api_root
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(10.0, connect=5.0),
            headers={"Accept": "application/json"},
            auth=config.auth_tuple,
            follow_redirects=True,
        )
        self._sem = asyncio.Semaphore(concurrency)
        self._cache: dict[str, Any] = {}
        self._max_retries = max_retries
        self._backoff_base = backoff_base

    async def aclose(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> BppClient:
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.aclose()

    def _full_url(self, url: str, params: dict | None = None) -> httpx.URL:
        """Zbuduj pełny URL: bezwzględny przyjmujemy wprost, względny
        doklejamy do korzenia API. ``params`` mergujemy w query string."""
        if url.startswith("http://") or url.startswith("https://"):
            full = httpx.URL(url)
        else:
            full = httpx.URL(f"{self._api_root}/{url.lstrip('/')}")
        if params:
            czyste = {k: v for k, v in params.items() if v is not None}
            if czyste:
                full = full.copy_merge_params(czyste)
        return full

    async def _request(self, full: httpx.URL) -> Any:
        """Wykonaj GET z retry×N i backoffem. Zwraca zdeserializowany JSON."""
        ostatni: Exception | None = None
        for proba in range(self._max_retries + 1):
            async with self._sem:
                try:
                    resp = await self._client.get(full)
                except httpx.HTTPError as exc:
                    # Błąd transportu (connect/read/timeout) — kwalifikuje do retry.
                    ostatni = exc
                else:
                    if resp.status_code == 404:
                        raise BppNotFound(
                            f"Zasób nie istnieje lub jest niewidoczny: {full}"
                        )
                    if resp.status_code >= 500:
                        ostatni = BppNetworkError(
                            f"Serwer BPP zwrócił {resp.status_code} dla {full}"
                        )
                    else:
                        try:
                            resp.raise_for_status()
                        except httpx.HTTPStatusError as exc:
                            raise BppError(
                                f"Błąd HTTP {resp.status_code} dla {full}"
                            ) from exc
                        return resp.json()
            if proba < self._max_retries:
                await asyncio.sleep(self._backoff_base * (proba + 1))
        raise BppNetworkError(
            f"Nie udało się pobrać {full} po {self._max_retries + 1} próbach: {ostatni}"
        ) from ostatni

    async def get_json(
        self, url: str, params: dict | None = None, *, use_cache: bool = True
    ) -> Any:
        """Pobierz i zdeserializuj JSON. Procesowy cache po pełnym URL-u."""
        full = self._full_url(url, params)
        klucz = str(full)
        if use_cache and klucz in self._cache:
            return self._cache[klucz]
        dane = await self._request(full)
        if use_cache:
            self._cache[klucz] = dane
        return dane

    async def get_paginated(
        self, path: str, params: dict | None = None, limit: int = 25
    ) -> list[Any]:
        """Auto-follow paginacji ``LimitOffset`` do zebrania ``limit`` pozycji.

        Podąża za ``next`` (bezwzględny URL z kolejnym ``offset``) aż do
        wyczerpania stron (``next == null``) lub osiągnięcia ``limit``.
        Strony list nie są cache'owane (zmienne, jednorazowe).
        """
        zebrane: list[Any] = []
        query = dict(params or {})
        query["limit"] = limit
        url: str | None = path
        pierwsza = True
        while url is not None and len(zebrane) < limit:
            if pierwsza:
                dane = await self.get_json(url, params=query, use_cache=False)
                pierwsza = False
            else:
                dane = await self.get_json(url, use_cache=False)
            if not isinstance(dane, dict):
                break
            zebrane.extend(dane.get("results", []))
            url = dane.get("next")
        return zebrane[:limit]
