"""Asynchroniczny klient HTTP dla API BPP.

Cechy (wg specu Fazy 2):

* jeden współdzielony ``httpx.AsyncClient`` (zakładany w lifespanie serwera),
* ``timeout = Timeout(10.0, connect=5.0)``,
* nagłówek ``Accept: application/json`` (NIE ``?format=json``),
* retry×2 z narastającym backoffem na błędy sieciowe / 5xx (GET jest
  idempotentny),
* semafor współbieżności (domyślnie 8) — ogranicza równoległe rozwijanie
  hyperlinków w :func:`bpp_mcp.tools.pobierz_rekord`,
* procesowy cache ``URL → JSON`` OGRANICZONY do białej listy prefiksów
  słownikowo-referencyjnych (:data:`bpp_mcp.catalog.PREFIKSY_CACHOWALNE` —
  jednostka/źródło/wydawca/słowniki). Rekordy publikacji, streszczenia,
  through-autorzy i raporty ``recent_*`` NIE są cache'owane (dane zmienne /
  jednorazowe → cache tylko by puchł i groził staleness),
* auto-follow paginacji ``LimitOffset`` porcjami po ``PAGE_LIMIT`` do zadanego
  ``limit`` (z twardym sufitem liczby stron — bezpiecznik przed zapętleniem),
* mapowanie 404 na czytelny :class:`BppNotFound` zamiast tracebacku; przy 4xx
  do komunikatu dołączamy fragment ciała odpowiedzi (wskazówka walidacji DRF).

Żadnego bare ``except`` — łapiemy wąskie typy httpx i re-raise'ujemy sensowny
błąd domenowy.
"""

from __future__ import annotations

import asyncio
from typing import Any

import httpx

from .auth import current_bearer
from .catalog import PREFIKSY_CACHOWALNE

# Rozmiar pojedynczej strony przy auto-follow paginacji. Stronicujemy porcjami
# zamiast żądać całego ``limit`` jednym requestem — chroni instancję BPP przed
# skrajnie dużym ``?limit=`` (BPP nie deklaruje ``max_limit`` po stronie DRF).
PAGE_LIMIT = 50


class BppError(Exception):
    """Bazowy, czytelny błąd domenowy zwracany narzędziom MCP.

    Gdy błąd pochodzi z odpowiedzi HTTP (4xx/5xx), niesie ``status_code`` oraz
    (dla 4xx z ciałem JSON) zdeserializowany ``payload`` — narzędzia mapują je
    na sensowne komunikaty (np. 400 DjangoQL → pozycja błędu, 503 → „zawęź").
    """

    def __init__(
        self, *args: object, status_code: int | None = None, payload: Any = None
    ) -> None:
        super().__init__(*args)
        self.status_code = status_code
        self.payload = payload


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
        self._auth_tuple = config.auth_tuple
        self._transport = config.transport
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(10.0, connect=5.0),
            headers={"Accept": "application/json"},
            follow_redirects=True,
        )
        self._sem = asyncio.Semaphore(concurrency)
        self._cache: dict[str, Any] = {}
        self._max_retries = max_retries
        self._backoff_base = backoff_base

    async def aclose(self) -> None:
        await self._client.aclose()

    @property
    def transport(self) -> str:
        """Tryb transportu (``stdio``/``http``) — steruje hybrydową
        podpowiedzią logowania w narzędziach zapytań DjangoQL."""
        return self._transport

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

    def _auth_kwargs(self) -> dict[str, Any]:
        """Per-request auth. Bearer (bieżący request) wygrywa zawsze. W trybie
        http brak bearera = błąd (żadnego cichego fallbacku na konto serwisowe).
        W stdio: Basic (gdy skonfigurowany) albo anonimowo."""
        bearer = current_bearer()
        if bearer:
            return {"headers": {"Authorization": f"Bearer {bearer}"}}
        if self._transport == "http":
            raise BppError(
                "Brak tokenu OAuth w kontekście żądania (tryb http) — nie "
                "forwarduję anonimowo ani przez konto serwisowe."
            )
        if self._auth_tuple:
            return {"auth": self._auth_tuple}
        return {}

    async def _request(self, full: httpx.URL, *, retry_5xx: bool = True) -> Any:
        """Wykonaj GET z retry×N i backoffem. Zwraca zdeserializowany JSON.

        ``retry_5xx=False`` wyłącza ponawianie na 5xx (błąd sieci nadal jest
        ponawiany) — używane przez zapytania DjangoQL, bo 503 = deterministyczny
        ``statement_timeout``, więc ponawianie tylko 3× re-uruchamiałoby ten sam
        wolny SQL.
        """
        auth_kwargs = self._auth_kwargs()
        ostatni: Exception | None = None
        for proba in range(self._max_retries + 1):
            async with self._sem:
                try:
                    resp = await self._client.get(full, **auth_kwargs)
                except httpx.HTTPError as exc:
                    # Błąd transportu (connect/read/timeout) — kwalifikuje do retry.
                    ostatni = exc
                else:
                    if resp.status_code == 404:
                        raise BppNotFound(
                            f"Zasób nie istnieje lub jest niewidoczny: {full}"
                        )
                    if resp.status_code >= 500:
                        blad_5xx = BppNetworkError(
                            f"Serwer BPP zwrócił {resp.status_code} dla {full}",
                            status_code=resp.status_code,
                        )
                        # ``retry_5xx=False`` → od razu podnosimy (bez ponawiania
                        # deterministycznego 503 statement_timeout).
                        if not retry_5xx:
                            raise blad_5xx
                        ostatni = blad_5xx
                    else:
                        try:
                            resp.raise_for_status()
                        except httpx.HTTPStatusError as exc:
                            # 4xx: dołącz fragment ciała odpowiedzi — DRF zwraca
                            # tam komunikat walidacji (np. że charakter_formalny
                            # oczekuje PK ze slownik(...)), co jest wskazówką dla
                            # LLM-a. Bez tego zostawał sam suchy kod stanu.
                            tresc = " ".join(resp.text.split())[:300]
                            dodatek = f" — {tresc}" if tresc else ""
                            try:
                                # Ciało 4xx bywa JSON-em (DjangoQL 400:
                                # {error,line,column,mark}) — zachowaj strukturę.
                                payload = resp.json()
                            except ValueError:
                                payload = None
                            raise BppError(
                                f"Błąd HTTP {resp.status_code} dla {full}{dodatek}",
                                status_code=resp.status_code,
                                payload=payload,
                            ) from exc
                        return resp.json()
            if proba < self._max_retries:
                await asyncio.sleep(self._backoff_base * (proba + 1))
        raise BppNetworkError(
            f"Nie udało się pobrać {full} po {self._max_retries + 1} próbach: {ostatni}"
        ) from ostatni

    @staticmethod
    def _prefiks_cachowalny(full: httpx.URL) -> bool:
        """Czy pierwszy segment ścieżki po ``/api/v1/`` jest na białej liście
        prefiksów wolno-cache'owalnych (:data:`PREFIKSY_CACHOWALNE`)."""
        segmenty = [s for s in full.path.split("/") if s]
        if "v1" in segmenty:
            idx = segmenty.index("v1")
            prefiks = segmenty[idx + 1] if idx + 1 < len(segmenty) else None
        else:
            prefiks = segmenty[0] if segmenty else None
        return prefiks in PREFIKSY_CACHOWALNE

    async def get_json(
        self,
        url: str,
        params: dict | None = None,
        *,
        use_cache: bool = True,
        retry_5xx: bool = True,
    ) -> Any:
        """Pobierz i zdeserializuj JSON.

        Cache procesowy po pełnym URL-u działa TYLKO gdy ``use_cache`` jest
        prawdą ORAZ prefiks endpointu jest na białej liście
        :data:`PREFIKSY_CACHOWALNE` (słowniki, jednostki, źródła, wydawcy).
        Rekordy publikacji, streszczenia i through-autorzy nie trafiają do
        cache nawet przy ``use_cache=True`` — cache nie rośnie w nieskończoność.
        """
        full = self._full_url(url, params)
        klucz = str(full)
        cachowalne = use_cache and self._prefiks_cachowalny(full)
        if cachowalne and klucz in self._cache:
            return self._cache[klucz]
        dane = await self._request(full, retry_5xx=retry_5xx)
        if cachowalne:
            self._cache[klucz] = dane
        return dane

    async def get_paginated(
        self,
        path: str,
        params: dict | None = None,
        limit: int = 25,
        *,
        page_limit: int = PAGE_LIMIT,
        retry_5xx: bool = True,
    ) -> tuple[list[Any], int, bool]:
        """Auto-follow paginacji ``LimitOffset`` do zebrania ``limit`` pozycji.

        Stronicuje porcjami po ``min(page_limit, limit)`` (NIE żąda całego
        ``limit`` jednym requestem — chroni instancję BPP), podążając za
        ``next`` aż do wyczerpania stron (``next == null``) lub osiągnięcia
        ``limit``. Strony list nie są cache'owane (zmienne, jednorazowe).

        Zwraca krotkę ``(zebrane, laczna_liczba, niepelne)``:

        * ``laczna_liczba`` — serwerowy ``count`` z pierwszej strony
          (rzeczywista liczba trafień po stronie BPP, ≠ ``len(zebrane)`` przy
          obcięciu do ``limit``),
        * ``niepelne`` — ``True`` gdy pętlę przerwał BEZPIECZNIK (sufit liczby
          stron / powtórzony ``next``) mimo że ``next`` był wciąż niepusty, więc
          pobranie mogło NIE objąć wszystkiego, co było w zasięgu ``limit``.
          ``False`` przy naturalnym końcu (``next == null``) lub dobiciu limitu.

        Bezpieczniki przed zapętleniem zbugowanego serwera:

        * twardy sufit liczby stron (``limit // per_page + 2``),
        * przerwanie, gdy ``next`` wskazuje na dokładnie ten sam URL co przed
          chwilą, albo gdy strona nie wniosła żadnych nowych pozycji.
        """
        per_page = max(1, min(page_limit, limit))
        maks_stron = limit // per_page + 2
        zebrane: list[Any] = []
        laczna: int | None = None
        query = dict(params or {})
        query["limit"] = per_page
        url: str | None = path
        pierwsza = True
        poprzedni_url: str | None = None
        strony = 0
        niepelne = False
        while url is not None and len(zebrane) < limit:
            if strony >= maks_stron or url == poprzedni_url:
                # Przerwanie przez bezpiecznik (NIE naturalne next=null ani
                # dobicie limitu): ``next`` wciąż wskazuje kolejną stronę, ale
                # zatrzymujemy się, by nie zapętlić się na zbugowanym serwerze.
                # Sygnalizujemy, że pobranie może być niepełne.
                niepelne = True
                break
            poprzedni_url = url
            if pierwsza:
                dane = await self.get_json(
                    url, params=query, use_cache=False, retry_5xx=retry_5xx
                )
                pierwsza = False
            else:
                dane = await self.get_json(url, use_cache=False, retry_5xx=retry_5xx)
            strony += 1
            if not isinstance(dane, dict):
                break
            if laczna is None and isinstance(dane.get("count"), int):
                laczna = dane["count"]
            nowe = dane.get("results", [])
            if not nowe:
                break
            zebrane.extend(nowe)
            url = dane.get("next")
        zebrane = zebrane[:limit]
        if laczna is None:
            laczna = len(zebrane)
        return zebrane, laczna, niepelne
