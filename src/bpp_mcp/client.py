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
from enum import Enum
from typing import Any

import httpx

from .auth import current_bearer
from .catalog import PREFIKSY_CACHOWALNE

# Rozmiar pojedynczej strony przy auto-follow paginacji. Stronicujemy porcjami
# zamiast żądać całego ``limit`` jednym requestem — pojedyncze żądanie zostaje
# małe niezależnie od tego, ile pozycji zamówiło narzędzie. BPP deklaruje własny
# sufit po stronie DRF (``api_v1.pagination.BppLimitOffsetPagination``,
# ``MAKS_LIMIT = 500``), ale jest to CICHY clamp: większe ``?limit=`` nie jest
# błędem — serwer oddaje 200 z 500 pozycjami i ``next``. Nie zwalnia nas to więc
# ze stronicowania, tym bardziej że ten klient łączy się z dowolną instancją
# BPP, a te bywają w różnych wersjach (starsze cap-a nie mają wcale).
PAGE_LIMIT = 50


class TrybAuth(str, Enum):
    """Polityka uwierzytelniania żądań do API BPP — jawnie, zamiast wnioskowania
    z nazwy transportu.

    * :attr:`LOKALNY` (stdio) — bearer z kontekstu żądania, a gdy go brak:
      Basic ze zmiennej ``BPP_BASIC_AUTH`` (jeśli skonfigurowany), a w
      ostateczności anonimowo. To tryb narzędzia uruchamianego przez samego
      użytkownika na jego maszynie: konto z Basica jest JEGO kontem.
    * :attr:`ZDALNY` (http) — WYŁĄCZNIE bearer bieżącego żądania; jego brak to
      błąd. Serwer obsługuje wielu użytkowników naraz, więc cichy fallback na
      konto serwisowe albo na anonima oddawałby jednemu użytkownikowi dane
      wyjęte spod uprawnień kogoś innego.
    * :attr:`W_PROCESIE` — bearer bieżącego żądania albo anonimowo; Basic jest
      ZABRONIONY, nawet gdy skonfigurowany.

    Dlaczego :attr:`W_PROCESIE` nie dopuszcza Basica: w tym trybie BPP hostuje
    endpoint MCP samo i woła własne API w procesie, dla cudzych żądań. Nie ma
    tam „konta serwisowego" w sensie właściciela danych — Basic byłby kontem
    JAKIEGOŚ użytkownika, wspólnym dla wszystkich wywołań. Poszedłby więc obok
    całego toru autoryzacji OAuth: z pominięciem scope'ów przyznanych tokenowi
    i bez możliwości odebrania dostępu (revoke tokenu nic by nie zmienił, bo
    request i tak wykonałby się na Basicu). Anonim jest bezpieczny — widzi
    dokładnie to, co publiczna część bibliografii — więc to on jest fallbackiem.
    """

    LOKALNY = "stdio"
    ZDALNY = "http"
    W_PROCESIE = "w-procesie"

    @classmethod
    def z_transportu(cls, transport: str) -> TrybAuth:
        """Wyprowadź tryb z ``config.transport`` — dokładnie tak, jak klient
        rozstrzygał to przed wprowadzeniem enumeracji: ``http`` → :attr:`ZDALNY`,
        cokolwiek innego → :attr:`LOKALNY`. Trybu :attr:`W_PROCESIE` nie da się
        wyprowadzić z konfiguracji; host podaje go jawnie w konstruktorze."""
        return cls.ZDALNY if transport == "http" else cls.LOKALNY


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
        transport: httpx.AsyncBaseTransport | None = None,
        tryb_auth: TrybAuth | None = None,
    ) -> None:
        """Zbuduj klienta dla instancji opisanej przez ``config``.

        ``transport`` podstawia warstwę transportową ``httpx`` — ``None`` (dom.)
        zostawia domyślny transport sieciowy. Szew istnieje dla hostowania
        w procesie: BPP przekazuje tu ``httpx.ASGITransport`` i żądania trafiają
        wprost do własnej aplikacji Django, bez pętli po sieci (a więc bez
        drugiego workera, bez TLS-a i bez adresu, który trzeba znać).

        ``tryb_auth`` wybiera politykę uwierzytelniania (:class:`TrybAuth`).
        ``None`` (dom.) wyprowadza ją z ``config.transport``, czyli odtwarza
        zachowanie sprzed wprowadzenia enumeracji.
        """
        self._api_root = config.api_root
        self._auth_tuple = config.auth_tuple
        self._transport = config.transport
        # KOERCJA, nie samo przypisanie. ``TrybAuth`` ma mixin ``str``, więc host
        # naturalnie poda tu string (np. z settings Django) — a ``_auth_kwargs``
        # porównuje przez ``is``, przy którym goły string NIE pasuje do żadnej
        # gałęzi i wypada na koniec, do Basica. Byłaby to cicha degradacja do
        # NAJBARDZIEJ permisywnej polityki, dokładnie w kodzie, który ma
        # pilnować, żeby Basic tam nie trafił. ``TrybAuth(...)`` przyjmuje
        # poprawną wartość i rzuca ``ValueError`` na nieznanej.
        self._tryb_auth = (
            TrybAuth(tryb_auth)
            if tryb_auth is not None
            else TrybAuth.z_transportu(config.transport)
        )
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(10.0, connect=5.0),
            headers={"Accept": "application/json"},
            follow_redirects=True,
            transport=transport,
        )
        self._sem = asyncio.Semaphore(concurrency)
        self._cache: dict[str, Any] = {}
        self._max_retries = max_retries
        self._backoff_base = backoff_base

    async def aclose(self) -> None:
        await self._client.aclose()

    @property
    def transport(self) -> str:
        """Surowa wartość ``config.transport`` (``stdio``/``http``).

        Niczym już po stronie klienta NIE steruje: politykę uwierzytelniania
        niesie :attr:`tryb_auth`, a treść podpowiedzi logowania po 401 —
        również ona (``tools._zapytanie``). Zostaje jako odczyt konfiguracji,
        bo pakiet jest na PyPI; nowy kod ma sięgać po :attr:`tryb_auth`."""
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

    @property
    def tryb_auth(self) -> TrybAuth:
        """Obowiązująca polityka uwierzytelniania (:class:`TrybAuth`)."""
        return self._tryb_auth

    def _auth_kwargs(self) -> dict[str, Any]:
        """Per-request auth wg :class:`TrybAuth`. Bearer bieżącego żądania
        wygrywa zawsze; reszta zależy od trybu (uzasadnienia — patrz
        :class:`TrybAuth`)."""
        bearer = current_bearer()
        if bearer:
            return {"headers": {"Authorization": f"Bearer {bearer}"}}
        if self._tryb_auth is TrybAuth.ZDALNY:
            raise BppError(
                "Brak tokenu OAuth w kontekście żądania (TrybAuth.ZDALNY) — "
                "nie forwarduję anonimowo ani przez konto serwisowe."
            )
        if self._tryb_auth is TrybAuth.W_PROCESIE:
            # Świadomie POMIJAMY Basic: w hostowaniu w procesie byłby wspólnym
            # kontem omijającym scope i revoke tokenu. Zostaje anonim.
            return {}
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

    def _slownik_cache(self) -> dict[str, Any]:
        """Zwróć słownik, w którym trzymamy cache ``URL → JSON``.

        Szew do nadpisania w podklasie. Domyślnie jeden słownik na instancję
        klienta, co jest poprawne dla procesu obsługującego jednego użytkownika
        i jedną instancję BPP (stdio, ``bpp-mcp --http`` z jednym ``BPP_BASE_URL``).

        Przy hostowaniu w procesie klient żyje w lifespan-kontekście serwera
        MCP, a w SDK 2.0 lifespan wchodzi RAZ na serwer (nie per sesja), więc
        jest WSPÓŁDZIELONY przez cały proces — a klucz cache to sam URL.
        Jeden słownik obsługiwałby wtedy wszystkich użytkowników i (w instalacji
        wielo-tenantowej) wszystkie uczelnie naraz, więc odpowiedź przygotowana
        dla jednego żądania trafiałaby do następnego. Host podstawia tu słownik
        o właściwym zasięgu (np. per-żądanie, z ContextVar)."""
        return self._cache

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
        cache = self._slownik_cache()
        if cachowalne and klucz in cache:
            return cache[klucz]
        dane = await self._request(full, retry_5xx=retry_5xx)
        if cachowalne:
            cache[klucz] = dane
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
