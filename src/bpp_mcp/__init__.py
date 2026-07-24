"""Serwer MCP dla API BPP (Bibliografia Publikacji Pracowników).

Wystawia read-only API BPP (`/api/v1/`) jako kuratorowane narzędzia MCP:
wyszukiwanie publikacji i autorów, pobieranie rozwiniętych rekordów
(z autorami/źródłem/streszczeniami zamiast hyperlinków), harvest list
publikacji oraz małe słowniki referencyjne.
"""

__version__ = "0.1.1"

__all__ = ["__version__"]
