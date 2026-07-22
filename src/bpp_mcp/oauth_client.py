"""OAuth 2.1 public client (native-app flow, RFC 8252) dla trybu stdio.

Kroki rozbite na małe, osobno testowalne funkcje: ``discover`` (AS-metadata,
RFC 8414), ``register_client`` (DCR, RFC 7591), ``_pkce`` (S256),
``refresh`` (rotujący refresh) oraz ``login`` (orkiestracja loopback+browser).
Sieć przez ``httpx`` (wstrzykiwalny ``client`` do testów).
"""

from __future__ import annotations

import base64
import hashlib
import queue
import secrets
import sys
import threading
import time
import urllib.parse
import webbrowser
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, HTTPServer

import httpx

from .token_store import TokenSet

_TIMEOUT = httpx.Timeout(10.0, connect=5.0)


class RefreshFailed(Exception):
    """Odświeżenie tokenu nieudane (brak/nieważny refresh, sieć)."""


@dataclass
class Metadata:
    authorization_endpoint: str
    token_endpoint: str
    registration_endpoint: str | None


def _client_ctx(client: httpx.Client | None) -> tuple[httpx.Client, bool]:
    if client is not None:
        return client, False
    return httpx.Client(timeout=_TIMEOUT, follow_redirects=True), True


def _konwencjonalne(base_url: str) -> Metadata:
    """Ścieżki, pod którymi BPP montuje serwer autoryzacji (``oauth_mcp/urls.py``).

    Używane jako fallback, gdy metadanych RFC 8414 nie da się odczytać.
    """
    base = base_url.rstrip("/")
    return Metadata(
        authorization_endpoint=f"{base}/o/authorize/",
        token_endpoint=f"{base}/o/token/",
        registration_endpoint=f"{base}/o/register/",
    )


def discover(base_url: str, *, client: httpx.Client | None = None) -> Metadata:
    """Odczytaj metadane serwera autoryzacji (RFC 8414), z fallbackiem na ``/o/*``.

    Discovery bywa nieosiągalne mimo w pełni sprawnego serwera autoryzacji —
    typowo gdy brzegowy nginx blokuje cały ``/.well-known/`` regułą na pliki
    ukryte (``location ~ /\\.``) i oddaje 403. Że endpointy istnieją, widać
    dopiero po odpytaniu ``/o/authorize/``. Padanie w takim układzie znaczyłoby
    „nie da się zalogować", choć logowanie jest w pełni możliwe — dlatego
    wracamy na konwencjonalne ścieżki django-oauth-toolkit.

    Fallback jest bezpieczny: nie zgaduje sekretów ani hosta (zostajemy na
    ``base_url``), a gdy zgadnie źle, żądanie do ``/o/token/`` skończy się
    czytelnym błędem. Prawidłowe metadane ZAWSZE mają pierwszeństwo — instancja
    z serwerem autoryzacji pod innym adresem nie zostanie nadpisana.
    """
    url = f"{base_url.rstrip('/')}/.well-known/oauth-authorization-server"
    cli, owns = _client_ctx(client)
    try:
        resp = cli.get(url)
        resp.raise_for_status()
        data = resp.json()
        return Metadata(
            authorization_endpoint=data["authorization_endpoint"],
            token_endpoint=data["token_endpoint"],
            registration_endpoint=data.get("registration_endpoint"),
        )
    except (httpx.HTTPError, ValueError, KeyError, TypeError):
        # ValueError łapie też JSONDecodeError (HTML zamiast JSON), KeyError —
        # metadane bez wymaganych pól, TypeError — JSON niebędący obiektem.
        return _konwencjonalne(base_url)
    finally:
        if owns:
            cli.close()


def register_client(
    meta: Metadata,
    redirect_uri: str,
    *,
    client_name: str = "bpp-mcp",
    client: httpx.Client | None = None,
) -> str:
    if not meta.registration_endpoint:
        raise RuntimeError("Instancja BPP nie udostępnia rejestracji (DCR).")
    cli, owns = _client_ctx(client)
    try:
        resp = cli.post(
            meta.registration_endpoint,
            json={"client_name": client_name, "redirect_uris": [redirect_uri]},
        )
        if resp.status_code >= 400:
            tresc = " ".join(resp.text.split())[:300]
            raise RuntimeError(
                f"Rejestracja klienta odrzucona ({resp.status_code}): {tresc}"
            )
        return resp.json()["client_id"]
    finally:
        if owns:
            cli.close()


def _pkce() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return verifier, challenge


def _exchange(
    token_endpoint: str, data: dict, *, client: httpx.Client | None = None
) -> dict:
    cli, owns = _client_ctx(client)
    try:
        resp = cli.post(token_endpoint, data=data)
        resp.raise_for_status()
        return resp.json()
    finally:
        if owns:
            cli.close()


def _whoami(
    base_url: str, access_token: str, *, client: httpx.Client | None = None
) -> str | None:
    cli, owns = _client_ctx(client)
    try:
        resp = cli.get(
            f"{base_url.rstrip('/')}/api/v1/whoami/",
            headers={
                "Authorization": f"Bearer {access_token}",
                "Accept": "application/json",
            },
        )
        if resp.status_code != 200:
            return None
        return resp.json().get("username")
    except httpx.HTTPError:
        return None  # tożsamość jest miękka — nie wywraca loginu
    finally:
        if owns:
            cli.close()


def refresh(ts: TokenSet, *, client: httpx.Client | None = None) -> TokenSet:
    if not ts.refresh_token:
        raise RefreshFailed("Brak refresh_token — wymagane ponowne logowanie.")
    if not ts.client_id:
        raise RefreshFailed("Brak client_id — wymagane ponowne logowanie.")
    try:
        tok = _exchange(
            ts.token_endpoint,
            {
                "grant_type": "refresh_token",
                "refresh_token": ts.refresh_token,
                "client_id": ts.client_id,
            },
            client=client,
        )
    except httpx.HTTPStatusError as exc:
        raise RefreshFailed(
            f"Odświeżenie odrzucone ({exc.response.status_code})."
        ) from exc
    except httpx.HTTPError as exc:
        raise RefreshFailed(f"Błąd sieci przy odświeżaniu: {exc}") from exc
    return TokenSet(
        base_url=ts.base_url,
        access_token=tok["access_token"],
        refresh_token=tok.get("refresh_token") or ts.refresh_token,
        expires_at=time.time() + float(tok.get("expires_in", 0)),
        token_endpoint=ts.token_endpoint,
        username=ts.username,
        client_id=ts.client_id,
    )


_STRONA_OK = (
    "<!doctype html><meta charset='utf-8'>"
    "<h1>Zalogowano do BPP</h1><p>Możesz wrócić do Claude i zamknąć tę kartę.</p>"
)


class _CallbackHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802 (API http.server)
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path != "/callback":
            self.send_response(404)
            self.end_headers()
            return
        params = urllib.parse.parse_qs(parsed.query)
        # Drugi element krotki to „czy to ręczna wklejka" — z loopbacku ZAWSZE
        # False. Znacznik jedzie obok parametrów, nigdy w nich, bo query string
        # pochodzi z sieci i użytkownik go nie kontroluje.
        self.server.wynik.put((params, False))  # type: ignore[attr-defined]
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(_STRONA_OK.encode("utf-8"))

    def log_message(self, *args: object) -> None:
        pass  # cisza — nie zaśmiecaj stderr logami http.server


def _start_loopback() -> tuple[HTTPServer, int]:
    server = HTTPServer(("127.0.0.1", 0), _CallbackHandler)
    server.wynik = queue.Queue()  # type: ignore[attr-defined]
    port = server.server_address[1]
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, port


def _czytaj_stdin() -> str | None:
    """Zwróć pierwszą niepustą linię ze stdin (albo ``None`` przy EOF/braku).

    ``None`` przy EOF jest istotne: pod pytest/nie-interaktywnie stdin bywa
    zamknięty i odczyt wraca natychmiast — wtedy czytnik ma po prostu zamilknąć
    i zostawić decyzję pętli loopbacku, zamiast wrzucać pustkę do kolejki.
    """
    try:
        for linia in sys.stdin:
            if linia.strip():
                return linia
    except (OSError, ValueError):
        return None
    return None


def _parsuj_wklejone(tekst: str) -> tuple[dict[str, list[str]], bool]:
    """Zamień wklejkę użytkownika na ``(parametry, czy_goly_kod)``.

    Przyjmuje pełny adres przekierowania (``http://127.0.0.1:…?code=…&state=…``)
    albo sam kod. Flaga wraca OSOBNO, a nie jako klucz w parametrach: parametry
    bywają budowane z danych sieciowych (callback na loopbacku), więc wszystko,
    co w nich siedzi, trzeba traktować jak wejście kontrolowane przez atakującego.
    Znacznik trzymany w tym samym słowniku dałby się podszyć żądaniem
    ``?code=…&_recznie=1`` i ominąć kontrolę ``state``.
    """
    tekst = tekst.strip()
    if not tekst:
        return {}, False
    if "?" in tekst:
        return urllib.parse.parse_qs(urllib.parse.urlparse(tekst).query), False
    return {"code": [tekst]}, True


def _start_czytnik(kolejka: queue.Queue, czytaj) -> None:
    """Wątek-demon czekający na wklejkę; wrzuca wynik do tej samej kolejki,
    w którą celuje loopback — kto pierwszy, ten wygrywa."""

    def _pracuj() -> None:
        try:
            tekst = czytaj()
        except Exception:  # czytnik jest opcjonalną wygodą — nie wywraca loginu
            return
        if not tekst:
            return
        params, goly_kod = _parsuj_wklejone(tekst)
        if params.get("code") or params.get("error"):
            kolejka.put((params, goly_kod))

    threading.Thread(target=_pracuj, daemon=True).start()


_INSTRUKCJA = (
    "Jeśli przeglądarka otworzyła się na innej maszynie niż ta, callback na "
    "127.0.0.1 tu nie wróci.\nPo zalogowaniu skopiuj wtedy z paska adresu CAŁY "
    "adres przekierowania (zaczyna się od\nhttp://127.0.0.1:) albo sam parametr "
    "code — wklej poniżej i naciśnij Enter."
)


def login(
    base_url: str,
    *,
    existing_client_id: str | None = None,
    timeout: float = 300.0,
    open_browser=webbrowser.open,
    echo=print,
    czytaj_wklejone=None,
) -> TokenSet:
    """Przeprowadź logowanie OAuth 2.1 (loopback + PKCE) i zwróć zestaw tokenów.

    Domykane dwiema drogami naraz: przeglądarka odbija się na lokalny loopback
    (ścieżka automatyczna), a równolegle akceptowana jest wklejka użytkownika
    (ścieżka ratunkowa, gdy przeglądarka biegnie na innej maszynie — praca
    zdalna, SSH, serwer bez GUI). Wygrywa ta, która przyjdzie pierwsza.
    """
    base_url = base_url.rstrip("/")
    meta = discover(base_url)
    server, port = _start_loopback()
    redirect_uri = f"http://127.0.0.1:{port}/callback"
    try:
        client_id = existing_client_id or register_client(meta, redirect_uri)
        verifier, challenge = _pkce()
        state = secrets.token_urlsafe(32)
        query = urllib.parse.urlencode(
            {
                "response_type": "code",
                "client_id": client_id,
                "redirect_uri": redirect_uri,
                "scope": "read",
                "state": state,
                "code_challenge": challenge,
                "code_challenge_method": "S256",
            }
        )
        authorize_url = f"{meta.authorization_endpoint}?{query}"
        echo("")
        echo("Otwórz w przeglądarce i zaloguj się do BPP:")
        echo("")
        echo(f"    {authorize_url}")
        echo("")
        echo(_INSTRUKCJA)
        echo("")
        open_browser(authorize_url)
        _start_czytnik(server.wynik, czytaj_wklejone or _czytaj_stdin)  # type: ignore[attr-defined]
        try:
            params, goly_kod = server.wynik.get(timeout=timeout)  # type: ignore[attr-defined]
        except queue.Empty as exc:
            raise TimeoutError(
                "Nie odebrano odpowiedzi logowania w wyznaczonym czasie."
            ) from exc
        otrzymany_state = (params.get("state") or [None])[0]
        # Brak state wybaczamy TYLKO gdy użytkownik wkleił na stdin sam kod —
        # tam nie ma czego porównywać, a źródłem jest człowiek przy terminalu,
        # nie sieć. ``goly_kod`` przyjeżdża osobno od parametrów właśnie po to,
        # by żądanie na loopback nie mogło go sfabrykować. Na loopbacku
        # brak/niezgodność state pozostaje twardym odrzuceniem.
        if otrzymany_state != state and not (goly_kod and otrzymany_state is None):
            raise ValueError("Niezgodny parametr state — logowanie odrzucone.")
        code = (params.get("code") or [None])[0]
        if not code:
            blad = (params.get("error") or ["brak parametru code"])[0]
            raise ValueError(f"Logowanie nie powiodło się: {blad}.")
    finally:
        server.shutdown()
        server.server_close()
    tok = _exchange(
        meta.token_endpoint,
        {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri,
            "client_id": client_id,
            "code_verifier": verifier,
        },
    )
    return TokenSet(
        base_url=base_url,
        access_token=tok["access_token"],
        refresh_token=tok.get("refresh_token"),
        expires_at=time.time() + float(tok.get("expires_in", 0)),
        token_endpoint=meta.token_endpoint,
        username=_whoami(base_url, tok["access_token"]),
        client_id=client_id,
    )
