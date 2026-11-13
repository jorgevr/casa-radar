"""Gmail OAuth installed-app flow with PKCE and a loopback redirect (research R2, R3).

Three HTTP calls (authorise URL, code exchange, refresh) built on httpx and the standard
library. Errors carry method, path and status only; never tokens, codes or the client secret.
"""

from __future__ import annotations

import base64
import hashlib
import secrets
import socket
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Callable
from urllib.parse import parse_qs, urlencode, urlparse

import httpx

from app.mailbox import AuthRevoked, SourceUnavailable
from app.mailbox.credentials import Secret, load_client_secret, load_refresh_token, save_refresh_token

SCOPE = "https://www.googleapis.com/auth/gmail.readonly"
AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
AUTHORIZE_TIMEOUT_SECONDS = 300
HTTP_TIMEOUT_SECONDS = 30.0
EXPIRY_MARGIN_SECONDS = 60

_TOKEN_PATH = urlparse(TOKEN_URL).path

# In-memory access token cache: (token, monotonic deadline). Never persisted.
_cache: dict[str, object] = {"token": None, "deadline": 0.0}


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def make_code_verifier() -> str:
    return _b64url(secrets.token_bytes(48))


def code_challenge_for(verifier: str) -> str:
    return _b64url(hashlib.sha256(verifier.encode("ascii")).digest())


def build_authorization_url(*, client_id: str, redirect_uri: str, state: str, code_challenge: str) -> str:
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": SCOPE,
        "state": state,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
        "access_type": "offline",
        "prompt": "consent",
    }
    return f"{AUTH_URL}?{urlencode(params)}"


def _failure(status: int) -> str:
    return f"POST {_TOKEN_PATH} returned {status}"


def _post_token(data: dict, transport: httpx.BaseTransport | None, *, revoke_on_401: bool) -> dict:
    """POST to the token endpoint and map failures; messages hold method/path/status only."""
    try:
        with httpx.Client(transport=transport, timeout=HTTP_TIMEOUT_SECONDS) as client:
            response = client.post(TOKEN_URL, data=data)
    except httpx.HTTPError as exc:
        raise SourceUnavailable(f"POST {_TOKEN_PATH} failed: {type(exc).__name__}") from None
    status = response.status_code
    if status == 200:
        try:
            body = response.json()
        except ValueError:
            raise SourceUnavailable(f"POST {_TOKEN_PATH} returned 200 with an unreadable body") from None
        if not isinstance(body, dict) or not body.get("access_token"):
            raise SourceUnavailable(f"POST {_TOKEN_PATH} returned 200 without an access token")
        return body
    error = None
    if status == 400:
        try:
            error = response.json().get("error")
        except (ValueError, AttributeError):
            error = None
    if error == "invalid_grant" or (status == 401 and revoke_on_401):
        raise AuthRevoked(_failure(status)) from None
    raise SourceUnavailable(_failure(status)) from None


def exchange_code(
    *,
    client_id: str,
    client_secret: str,
    code: str,
    redirect_uri: str,
    code_verifier: str,
    transport: httpx.BaseTransport | None = None,
) -> dict:
    data = {
        "client_id": client_id,
        "client_secret": client_secret,
        "code": code,
        "redirect_uri": redirect_uri,
        "code_verifier": code_verifier,
        "grant_type": "authorization_code",
    }
    # No stored grant exists yet, so a 401 here is unavailability, not revocation.
    return _post_token(data, transport, revoke_on_401=False)


def refresh_access_token(
    *,
    client_id: str,
    client_secret: str,
    refresh_token: str,
    transport: httpx.BaseTransport | None = None,
) -> dict:
    data = {
        "client_id": client_id,
        "client_secret": client_secret,
        "refresh_token": refresh_token,
        "grant_type": "refresh_token",
    }
    return _post_token(data, transport, revoke_on_401=True)


def _wait_for_redirect(server: HTTPServer, timeout: float, state: str) -> dict[str, str]:
    """Serve loopback requests until one carries ``code`` or ``error`` with the expected ``state``.

    Requests with a wrong or missing state get a 400 and are ignored; the wait continues until the
    deadline. Each connection gets a socket timeout bounded by the time left, so an idle client
    cannot hold the wait past the deadline, and a timer closes any request still open at the deadline.
    """
    result: dict[str, str] = {}
    deadline = time.monotonic() + timeout

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            query = {k: v[0] for k, v in parse_qs(urlparse(self.path).query).items()}
            genuine = secrets.compare_digest(query.get("state", "").encode("utf-8"), state.encode("utf-8"))
            if ("code" in query or "error" in query) and not genuine:
                body = b"Bad request"
                self.send_response(400)
            elif "code" in query or "error" in query:
                result.update(query)
                body = "Autorizacion recibida. Puedes cerrar esta ventana.".encode("ascii")
                self.send_response(200)
            else:
                body = b"Not found"
                self.send_response(404)
            self.send_header("Content-Type", "text/plain; charset=us-ascii")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def handle(self) -> None:
            # Absolute deadline: a per-recv timeout is restarted by every byte a slow client
            # sends, so a timer shuts the connection down when the overall time is up.
            def abort() -> None:
                try:
                    self.request.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass

            timer = threading.Timer(max(deadline - time.monotonic(), 0.0), abort)
            timer.daemon = True
            timer.start()
            try:
                super().handle()
            finally:
                timer.cancel()

        def log_message(self, format: str, *args: object) -> None:  # noqa: A002
            return  # the request line carries the code; never log it

    server.RequestHandlerClass = Handler
    while not result:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        server.timeout = remaining
        Handler.timeout = remaining  # per-connection socket timeout (read by StreamRequestHandler)
        server.handle_request()
    return result


def authorize(
    *,
    open_browser: Callable[[str], object] = webbrowser.open,
    timeout: float = AUTHORIZE_TIMEOUT_SECONDS,
    transport: httpx.BaseTransport | None = None,
) -> None:
    """Run the consent flow in the system browser and store the refresh token."""
    client = load_client_secret()
    client_id = client["client_id"]
    client_secret = client.get("client_secret", "")
    verifier = make_code_verifier()
    state = secrets.token_urlsafe(24)
    server = HTTPServer(("127.0.0.1", 0), BaseHTTPRequestHandler)
    try:
        redirect_uri = f"http://127.0.0.1:{server.server_address[1]}/"
        url = build_authorization_url(
            client_id=client_id,
            redirect_uri=redirect_uri,
            state=state,
            code_challenge=code_challenge_for(verifier),
        )
        open_browser(url)
        params = _wait_for_redirect(server, timeout, state)
    finally:
        server.server_close()
    if not params:
        raise TimeoutError("authorisation was not completed within the time limit")
    if params.get("error"):
        raise PermissionError(f"authorisation refused: {params['error']}")
    if not secrets.compare_digest(params.get("state", ""), state):
        raise PermissionError("authorisation response had an unexpected state")
    tokens = exchange_code(
        client_id=client_id,
        client_secret=client_secret,
        code=params["code"],
        redirect_uri=redirect_uri,
        code_verifier=verifier,
        transport=transport,
    )
    refresh = tokens.get("refresh_token")
    if not refresh:
        raise SourceUnavailable("token endpoint returned no refresh token; revoke the app grant and retry")
    save_refresh_token(Secret(refresh))
    _store(tokens)


def _store(tokens: dict) -> str:
    token = tokens["access_token"]
    try:
        lifetime = float(tokens.get("expires_in", 0))
    except (TypeError, ValueError):
        lifetime = 0.0
    _cache["token"] = token
    _cache["deadline"] = time.monotonic() + lifetime - EXPIRY_MARGIN_SECONDS
    return token


def clear_cache() -> None:
    _cache["token"] = None
    _cache["deadline"] = 0.0


def access_token(*, transport: httpx.BaseTransport | None = None) -> str:
    """Return a valid access token, refreshing when the cached one is missing or near expiry."""
    cached = _cache["token"]
    if cached and time.monotonic() < float(_cache["deadline"]):
        return str(cached)
    stored = load_refresh_token()
    if stored is None:
        raise AuthRevoked("no refresh token stored; run mailbox-setup")
    client = load_client_secret()
    tokens = refresh_access_token(
        client_id=client["client_id"],
        client_secret=client.get("client_secret", ""),
        refresh_token=stored.value,
        transport=transport,
    )
    rotated = tokens.get("refresh_token")
    if rotated and rotated != stored.value:
        save_refresh_token(Secret(rotated))
    return _store(tokens)
