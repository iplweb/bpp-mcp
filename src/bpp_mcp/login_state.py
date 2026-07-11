"""Dostarczanie Bearera dla żądań w trybie stdio.

``TokenProvider`` czyta token ze store, zwraca access-token, a przy wygaśnięciu
odświeża go POD ``asyncio.Lock`` (serializacja — rotujący refresh nie znosi
refreshu równoległego) i utrwala nowy zestaw. Store jest re-loadowany, gdy w
pamięci brak tokenu lub disk się rozjechał (login w trakcie sesji / inny proces
MCP na tym samym pliku). Sync refresh (``httpx``) idzie przez ``asyncio.to_thread``,
by nie blokować pętli zdarzeń.
"""

from __future__ import annotations

import asyncio
import sys

from . import oauth_client, token_store


class TokenProvider:
    def __init__(self, base_url: str, *, refresh_fn=oauth_client.refresh) -> None:
        self._base_url = base_url
        self._refresh_fn = refresh_fn
        self._lock = asyncio.Lock()
        self._ts = token_store.load(base_url)

    async def bearer(self) -> str | None:
        ts = self._ts
        if ts is not None and not ts.is_expired():
            return ts.access_token
        async with self._lock:
            # Token mógł się pojawić (bpp-mcp login w trakcie żywej sesji) lub
            # zmienić (inny proces MCP na tym samym store) po starcie — re-load.
            dysk = token_store.load(self._base_url)
            if dysk is not None and (
                self._ts is None or dysk.access_token != self._ts.access_token
            ):
                self._ts = dysk
            ts = self._ts
            if ts is None:
                return None
            if not ts.is_expired():
                return ts.access_token
            try:
                nowy = await asyncio.to_thread(self._refresh_fn, ts)
            except oauth_client.RefreshFailed as exc:
                # Nie kasuj świeżego tokenu, który zdążył zapisać inny proces.
                dysk = token_store.load(self._base_url)
                if dysk is not None and dysk.access_token != ts.access_token:
                    self._ts = dysk
                    if not dysk.is_expired():
                        return dysk.access_token
                token_store.clear(self._base_url)
                self._ts = None
                print(
                    f"bpp-mcp: sesja wygasła ({exc}) — tryb anonimowy. "
                    "Zaloguj ponownie: bpp-mcp login",
                    file=sys.stderr,
                )
                return None
            token_store.save(nowy)
            self._ts = nowy
            return nowy.access_token
