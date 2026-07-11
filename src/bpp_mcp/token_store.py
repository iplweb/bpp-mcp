"""Trwały, per-instancja cache tokenów OAuth (tryb stdio self-login).

Plik ``~/.config/bpp-mcp/<sha256(base_url)[:16]>/tokens.json`` (chmod 600,
katalog 700, zapis atomowy). Klucz per-instancja izoluje tożsamości różnych
wdrożeń BPP. Bez I/O sieciowego — to tylko warstwa dyskowa.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from dataclasses import asdict, dataclass
from pathlib import Path

_REQUIRED = ("base_url", "access_token", "expires_at", "token_endpoint")


@dataclass
class TokenSet:
    base_url: str
    access_token: str
    refresh_token: str | None
    expires_at: float
    token_endpoint: str
    username: str | None = None
    client_id: str | None = None

    def is_expired(self, skew: float = 60.0, *, now: float | None = None) -> bool:
        current = time.time() if now is None else now
        return self.expires_at - skew <= current


def _config_home() -> Path:
    xdg = os.environ.get("XDG_CONFIG_HOME")
    return Path(xdg) if xdg else Path.home() / ".config"


def store_path(base_url: str) -> Path:
    # Normalizacja trailing slash: BPP_BASE_URL="…/" i "…" muszą trafić w ten
    # sam plik (inaczej zapis i odczyt rozjeżdżają się po hashu — cichy anon).
    klucz = hashlib.sha256(base_url.rstrip("/").encode("utf-8")).hexdigest()[:16]
    return _config_home() / "bpp-mcp" / klucz / "tokens.json"


def load(base_url: str) -> TokenSet | None:
    path = store_path(base_url)
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
        return None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict) or any(k not in data for k in _REQUIRED):
        return None
    return TokenSet(
        base_url=data["base_url"],
        access_token=data["access_token"],
        refresh_token=data.get("refresh_token"),
        expires_at=float(data["expires_at"]),
        token_endpoint=data["token_endpoint"],
        username=data.get("username"),
        client_id=data.get("client_id"),
    )


def save(ts: TokenSet) -> None:
    path = store_path(ts.base_url)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(path.parent, 0o700)
    tmp = path.with_suffix(".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    os.fchmod(fd, 0o600)  # wymuś 0600 nawet gdy tmp istniał z luźniejszymi prawami
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(asdict(ts), fh)
    os.replace(tmp, path)  # atomowo; zachowuje 0600 z tmp


def clear(base_url: str) -> None:
    path = store_path(base_url)
    for p in (path, path.with_suffix(".tmp")):
        try:
            p.unlink()
        except FileNotFoundError:
            pass  # już usunięty — logout idempotentny
