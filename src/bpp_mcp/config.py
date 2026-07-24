"""Konfiguracja serwera MCP: bazowy URL instancji BPP oraz opcjonalny
BasicAuth (używany wyłącznie dla raportów slotów — poza rdzeniem v1).

Wielo-instancyjność: ta sama binarka obsługuje dowolne wdrożenie BPP
(umlub oraz inne), różnicowane przez zmienną środowiskową ``BPP_BASE_URL``.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

_BRAK_HOSTA = (
    "Nie ustawiono BPP_BASE_URL — nie wiadomo, z którą instancją BPP rozmawiać.\n"
    "Wskaż ją jawnie, np.:\n"
    "    BPP_BASE_URL=https://bpp.twoja-uczelnia.pl bpp-mcp\n"
    "W konfiguracji klienta MCP ustaw tę zmienną w sekcji `env`."
)


class BrakKonfiguracji(RuntimeError):
    """Brakuje obowiązkowego ustawienia — serwer nie ma prawa zgadywać."""


@dataclass(frozen=True)
class Config:
    """Niezmienny zestaw ustawień połączenia z instancją BPP."""

    base_url: str
    basic_auth: str | None = None
    transport: str = "stdio"
    http_host: str = "127.0.0.1"
    http_port: int = 8000
    resource_url: str | None = None

    @classmethod
    def from_env(cls) -> Config:
        """Zbuduj konfigurację ze zmiennych środowiskowych.

        - ``BPP_BASE_URL`` — bazowy URL instancji (WYMAGANY, bez domyślnego),
        - ``BPP_BASIC_AUTH`` — opcjonalny ``user:pass`` (raporty slotów),
        - ``BPP_MCP_TRANSPORT`` — ``stdio`` (dom.) | ``http`` (OAuth),
        - ``BPP_MCP_HTTP_HOST`` / ``BPP_MCP_HTTP_PORT`` — bind serwera HTTP,
        - ``BPP_MCP_RESOURCE_URL`` — nadpisanie pola ``resource`` w PRM.

        ``BPP_BASE_URL`` nie ma wartości domyślnej celowo. Każde wdrożenie BPP
        to inna uczelnia i inna bibliografia, więc zaszyty host oznaczałby, że
        użytkownik bez tej zmiennej dostaje cudze dane wyglądające na własne —
        błąd cichy i trudny do zauważenia. Lepiej nie wystartować.

        :raises BrakKonfiguracji: gdy ``BPP_BASE_URL`` jest pusty lub nieustawiony.
        """
        base = (os.environ.get("BPP_BASE_URL") or "").strip()
        if not base:
            raise BrakKonfiguracji(_BRAK_HOSTA)
        auth = os.environ.get("BPP_BASIC_AUTH") or None
        transport = os.environ.get("BPP_MCP_TRANSPORT", "stdio").lower()
        return cls(
            base_url=base,
            basic_auth=auth,
            transport="http" if transport == "http" else "stdio",
            http_host=os.environ.get("BPP_MCP_HTTP_HOST", "127.0.0.1"),
            http_port=int(os.environ.get("BPP_MCP_HTTP_PORT", "8000")),
            resource_url=os.environ.get("BPP_MCP_RESOURCE_URL") or None,
        )

    @property
    def api_root(self) -> str:
        """Korzeń API v1, bez końcowego ukośnika."""
        return f"{self.base_url.rstrip('/')}/api/v1"

    @property
    def effective_resource_url(self) -> str:
        """URL zasobu (pole ``resource`` w protected-resource-metadata).
        Domyślnie kanoniczny URI serwera streamable: host:port + ``/mcp``."""
        return self.resource_url or f"http://{self.http_host}:{self.http_port}/mcp"

    @property
    def auth_tuple(self) -> tuple[str, str] | None:
        """Rozbij ``user:pass`` na krotkę dla httpx (lub ``None``)."""
        if not self.basic_auth:
            return None
        user, _, password = self.basic_auth.partition(":")
        return (user, password)
