"""Serwer MCP dla API BPP (Bibliografia Publikacji Pracowników).

Wystawia read-only API BPP (`/api/v1/`) jako kuratorowane narzędzia MCP:
wyszukiwanie publikacji i autorów, pobieranie rozwiniętych rekordów
(z autorami/źródłem/streszczeniami zamiast hyperlinków), harvest list
publikacji oraz małe słowniki referencyjne.
"""

from typing import Any

__version__ = "0.4.0"

__all__ = ["KontekstApp", "__version__", "register_tools"]

# Szwy do hostowania narzędzi we własnym procesie (BPP wystawiające /mcp)
# re-eksportujemy LENIWIE. ``bpp_mcp.server`` przy imporcie czyta środowisko
# i buduje modułowy serwer MCPServer — gdyby samo ``import bpp_mcp`` to robiło,
# lekkie użycia w rodzaju ``from bpp_mcp.config import Config`` nagle
# ciągnęłyby cały SDK MCP. Ładujemy więc dopiero przy pierwszym sięgnięciu.
#
# Uwaga: ``server`` importuje ``__version__`` z tego modułu, więc eager import
# byłby dodatkowo cyklem.
_LENIWE = frozenset({"KontekstApp", "register_tools"})


def __getattr__(name: str) -> Any:
    if name in _LENIWE:
        from . import server

        return getattr(server, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> list[str]:
    return sorted(set(globals()) | _LENIWE)
