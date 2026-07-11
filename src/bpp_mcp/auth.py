"""Warstwa OAuth Resource Server: weryfikacja opaque tokenu BPP przez
``whoami`` oraz przekazanie tokenu BIEŻĄCEGO requestu do BppClient.

Token BPP jest OPAQUE (nie JWT) — weryfikacja tylko zdalnie przez
``GET /api/v1/whoami/``: 200 → ważny, 401/403 → nieważny (``None`` →
transportowy 401), inne/sieć/nie-JSON → :class:`WhoamiUnavailable` (BPP
niedostępne; materializuje się jako HTTP 500 — klient NIE robi re-auth).

UWAGA (K1): do passthrough NIE używamy ``get_access_token()`` — w stateful
streamable HTTP zwraca on token z chwili ``initialize`` (stale). Token
bieżącego requestu bierzemy z ``ctx.request_context.request`` (patrz
``server._client``) i mostkujemy przez ContextVar poniżej.
"""

from __future__ import annotations

import time
from contextvars import ContextVar

import httpx
from mcp.server.auth.provider import AccessToken

_current_bearer: ContextVar[str | None] = ContextVar(
    "bpp_mcp_current_bearer", default=None
)


class WhoamiUnavailable(Exception):
    """BPP niedostępne przy weryfikacji tokenu (nie-200/401/403, sieć, nie-JSON).

    Różne od ``None`` (token nieważny → re-auth): token mógł być ważny, więc
    nie wymuszamy re-autoryzacji — request kończy się błędem serwera (5xx).
    """


def set_current_bearer(token: str | None) -> None:
    """Zapisz token bieżącego requestu w kontekście (dla BppClient)."""
    _current_bearer.set(token)


def current_bearer() -> str | None:
    """Zwróć token bieżącego requestu z kontekstu (``None`` poza http)."""
    return _current_bearer.get()


def bearer_from_request(request) -> str | None:
    """Wyłuskaj surowy token z nagłówka ``Authorization: Bearer`` (lub None)."""
    if request is None:
        return None
    authz = request.headers.get("authorization", "")
    if authz.lower().startswith("bearer "):
        return authz.split(" ", 1)[1].strip()
    return None


class WhoamiTokenVerifier:
    """``TokenVerifier`` (protokół SDK) oparty o ``whoami`` BPP, z positive-cache.

    Cache (``ttl`` s) redukuje +1 request/wywołanie i wygładza blipy; ma eviction
    (usuwa wygasłe) i twardy cap ``max_entries`` (drop najstarszego), by proces
    nie akumulował zrewokowanych tokenów w nieskończoność.
    """

    def __init__(
        self, base_url: str, *, ttl: float = 30.0, max_entries: int = 256
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._ttl = ttl
        self._max_entries = max_entries
        self._cache: dict[str, tuple[AccessToken, float]] = {}

    async def verify_token(self, token: str) -> AccessToken | None:
        now = time.monotonic()
        cached = self._cache.get(token)
        if cached is not None and cached[1] > now:
            return cached[0]
        url = f"{self._base_url}/api/v1/whoami/"
        headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(10.0, connect=5.0), follow_redirects=True
            ) as client:
                resp = await client.get(url, headers=headers)
        except httpx.HTTPError as exc:
            raise WhoamiUnavailable(f"whoami niedostępne: {exc}") from exc
        if resp.status_code in (401, 403):
            return None
        if resp.status_code != 200:
            raise WhoamiUnavailable(f"whoami zwróciło {resp.status_code}")
        try:
            data = resp.json()
        except ValueError as exc:
            raise WhoamiUnavailable(f"whoami zwróciło nie-JSON: {exc}") from exc
        access = AccessToken(
            token=token,
            client_id="bpp-mcp",
            scopes=["read"],
            subject=str(data["id"]) if data.get("id") is not None else None,
            claims=data,
        )
        self._store(token, access, now)
        return access

    def _store(self, token: str, access: AccessToken, now: float) -> None:
        if len(self._cache) >= self._max_entries:
            for k in [k for k, (_, exp) in self._cache.items() if exp <= now]:
                del self._cache[k]
            while len(self._cache) >= self._max_entries:
                self._cache.pop(next(iter(self._cache)))
        self._cache[token] = (access, now + self._ttl)
