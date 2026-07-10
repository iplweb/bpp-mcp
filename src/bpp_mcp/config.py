"""Konfiguracja serwera MCP: bazowy URL instancji BPP oraz opcjonalny
BasicAuth (używany wyłącznie dla raportów slotów — poza rdzeniem v1).

Wielo-instancyjność: ta sama binarka obsługuje dowolne wdrożenie BPP
(umlub oraz inne), różnicowane przez zmienną środowiskową ``BPP_BASE_URL``.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

DEFAULT_BASE_URL = "https://bpp.umlub.pl"


@dataclass(frozen=True)
class Config:
    """Niezmienny zestaw ustawień połączenia z instancją BPP."""

    base_url: str = DEFAULT_BASE_URL
    basic_auth: str | None = None

    @classmethod
    def from_env(cls) -> Config:
        """Zbuduj konfigurację ze zmiennych środowiskowych.

        - ``BPP_BASE_URL`` — bazowy URL instancji (domyślnie umlub),
        - ``BPP_BASIC_AUTH`` — opcjonalny ``user:pass`` (raporty slotów).
        """
        base = os.environ.get("BPP_BASE_URL", DEFAULT_BASE_URL)
        auth = os.environ.get("BPP_BASIC_AUTH") or None
        return cls(base_url=base, basic_auth=auth)

    @property
    def api_root(self) -> str:
        """Korzeń API v1, bez końcowego ukośnika."""
        return f"{self.base_url.rstrip('/')}/api/v1"

    @property
    def auth_tuple(self) -> tuple[str, str] | None:
        """Rozbij ``user:pass`` na krotkę dla httpx (lub ``None``)."""
        if not self.basic_auth:
            return None
        user, _, password = self.basic_auth.partition(":")
        return (user, password)
