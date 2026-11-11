"""OAuth flow tests for mailbox Gmail access (T051).

Phase 9 tests-first: app.mailbox.oauth / app.mailbox do not exist yet, so tests
must fail with ModuleNotFoundError/ImportError for the missing module. No
network, no real Google, no browser. Tokens used here are obviously fake.
"""

from __future__ import annotations

import logging
from urllib.parse import parse_qs, urlparse

import httpx
import pytest


# Obviously fake values; never real secrets.
FAKE_CLIENT_ID = "fake-client-id.apps.googleusercontent.com"
FAKE_CLIENT_SECRET = "FAKE_CLIENT_SECRET_VALUE"
FAKE_AUTH_CODE = "FAKE_AUTH_CODE_VALUE"
FAKE_CODE_VERIFIER = "FAKE_CODE_VERIFIER_VALUE_1234567890"
FAKE_CODE_CHALLENGE = "FAKE_CODE_CHALLENGE_VALUE"
FAKE_STATE = "FAKE_STATE_VALUE"
FAKE_REFRESH_TOKEN = "FAKE_REFRESH_TOKEN_1//0abcdef"
FAKE_ACCESS_TOKEN = "FAKE_ACCESS_TOKEN_ya29.abcdef"
FAKE_ROTATED_REFRESH_TOKEN = "FAKE_REFRESH_TOKEN_1//0rotated"
TOKEN_URL = "https://oauth2.googleapis.com/token"
SCOPE = "https://www.googleapis.com/auth/gmail.readonly"


def _assert_no_tokens(text: str) -> None:
    for token in (
        FAKE_CLIENT_SECRET,
        FAKE_AUTH_CODE,
        FAKE_CODE_VERIFIER,
        FAKE_REFRESH_TOKEN,
        FAKE_ACCESS_TOKEN,
        FAKE_ROTATED_REFRESH_TOKEN,
    ):
        assert token not in text


def _assert_exception_has_no_tokens(excinfo: pytest.ExceptionInfo[BaseException]) -> None:
    _assert_no_tokens(str(excinfo.value))
    _assert_no_tokens(repr(excinfo.value))
    cause = excinfo.value.__cause__
    context = excinfo.value.__context__
    if cause is not None:
        _assert_no_tokens(str(cause))
        _assert_no_tokens(repr(cause))
    if context is not None:
        _assert_no_tokens(str(context))
        _assert_no_tokens(repr(context))


def test_authorize_url_has_only_gmail_readonly_scope_pkce_s256_offline_loopback_redirect_and_prompt_consent(
    no_network,
):
    # Expected API: build_authorization_url(...) returns the consent URL string.
    from app.mailbox.oauth import build_authorization_url

    redirect_uri = "http://127.0.0.1:43123/"
    url = build_authorization_url(
        client_id=FAKE_CLIENT_ID,
        redirect_uri=redirect_uri,
        state=FAKE_STATE,
        code_challenge=FAKE_CODE_CHALLENGE,
    )

    parsed = urlparse(url)
    qs = parse_qs(parsed.query)

    assert qs.get("scope") == [SCOPE]
    assert qs.get("code_challenge_method") == ["S256"]
    assert qs.get("access_type") == ["offline"]
    assert qs.get("prompt") == ["consent"]
    assert qs.get("redirect_uri") == [redirect_uri]
    # Redirect must be loopback as specified.
    redir = urlparse(qs["redirect_uri"][0])
    assert redir.scheme == "http"
    assert redir.hostname == "127.0.0.1"
    # No extra scopes or token leakage.
    assert " " not in qs["scope"][0]
    _assert_no_tokens(url.replace(FAKE_CODE_CHALLENGE, "").replace(FAKE_STATE, ""))
    # Silence linter-style unused warning for parsed base host; redirect is the contract.
    assert parsed.scheme in {"https", "http"}


def test_exchange_code_posts_to_token_endpoint(no_network):
    from app.mailbox.oauth import exchange_code

    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(
            200,
            json={
                "access_token": FAKE_ACCESS_TOKEN,
                "refresh_token": FAKE_REFRESH_TOKEN,
                "expires_in": 3600,
                "token_type": "Bearer",
            },
        )

    transport = httpx.MockTransport(handler)
    result = exchange_code(
        client_id=FAKE_CLIENT_ID,
        client_secret=FAKE_CLIENT_SECRET,
        code=FAKE_AUTH_CODE,
        redirect_uri="http://127.0.0.1:43123/",
        code_verifier=FAKE_CODE_VERIFIER,
        transport=transport,
    )

    assert len(seen) == 1
    req = seen[0]
    assert req.method == "POST"
    assert str(req.url) == TOKEN_URL
    # Caller receives tokens for storage/use (values come from response).
    assert result["access_token"] == FAKE_ACCESS_TOKEN
    assert result["refresh_token"] == FAKE_REFRESH_TOKEN


def test_refresh_posts_to_token_endpoint(no_network):
    from app.mailbox.oauth import refresh_access_token

    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(
            200,
            json={
                "access_token": FAKE_ACCESS_TOKEN,
                "expires_in": 3600,
                "token_type": "Bearer",
            },
        )

    transport = httpx.MockTransport(handler)
    result = refresh_access_token(
        client_id=FAKE_CLIENT_ID,
        client_secret=FAKE_CLIENT_SECRET,
        refresh_token=FAKE_REFRESH_TOKEN,
        transport=transport,
    )

    assert len(seen) == 1
    req = seen[0]
    assert req.method == "POST"
    assert str(req.url) == TOKEN_URL
    assert result["access_token"] == FAKE_ACCESS_TOKEN


def test_refresh_invalid_grant_raises_auth_revoked(no_network):
    from app.mailbox import AuthRevoked
    from app.mailbox.oauth import refresh_access_token

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"error": "invalid_grant"})

    transport = httpx.MockTransport(handler)
    with pytest.raises(AuthRevoked):
        refresh_access_token(
            client_id=FAKE_CLIENT_ID,
            client_secret=FAKE_CLIENT_SECRET,
            refresh_token=FAKE_REFRESH_TOKEN,
            transport=transport,
        )


def test_exchange_code_invalid_grant_raises_auth_revoked(no_network):
    from app.mailbox import AuthRevoked
    from app.mailbox.oauth import exchange_code

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"error": "invalid_grant"})

    transport = httpx.MockTransport(handler)
    with pytest.raises(AuthRevoked):
        exchange_code(
            client_id=FAKE_CLIENT_ID,
            client_secret=FAKE_CLIENT_SECRET,
            code=FAKE_AUTH_CODE,
            redirect_uri="http://127.0.0.1:43123/",
            code_verifier=FAKE_CODE_VERIFIER,
            transport=transport,
        )


def test_refresh_401_raises_auth_revoked(no_network):
    # mail-source contract: 401 after refresh -> AuthRevoked.
    from app.mailbox import AuthRevoked
    from app.mailbox.oauth import refresh_access_token

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": "unauthorized_client"})

    transport = httpx.MockTransport(handler)
    with pytest.raises(AuthRevoked):
        refresh_access_token(
            client_id=FAKE_CLIENT_ID,
            client_secret=FAKE_CLIENT_SECRET,
            refresh_token=FAKE_REFRESH_TOKEN,
            transport=transport,
        )


def test_token_endpoint_errors_expose_method_path_status_only_and_never_tokens(
    no_network, caplog
):
    # Contract names AuthRevoked for 401 after refresh; code-exchange 401 type is not
    # specified by contracts/task, so (AuthRevoked, SourceUnavailable) is accepted as an
    # open decision recorded in the handoff pending coordinator/user approval.
    from app.mailbox import AuthRevoked, SourceUnavailable
    from app.mailbox.oauth import exchange_code, refresh_access_token

    def handler(request: httpx.Request) -> httpx.Response:
        # Response body echoes sensitive values; implementation must not surface them.
        return httpx.Response(
            401,
            text=(
                f"denied secret={FAKE_CLIENT_SECRET} code={FAKE_AUTH_CODE} "
                f"refresh={FAKE_REFRESH_TOKEN} access={FAKE_ACCESS_TOKEN} "
                f"verifier={FAKE_CODE_VERIFIER}"
            ),
        )

    transport = httpx.MockTransport(handler)

    caplog.set_level(logging.DEBUG)
    with pytest.raises((AuthRevoked, SourceUnavailable)) as excinfo:
        exchange_code(
            client_id=FAKE_CLIENT_ID,
            client_secret=FAKE_CLIENT_SECRET,
            code=FAKE_AUTH_CODE,
            redirect_uri="http://127.0.0.1:43123/",
            code_verifier=FAKE_CODE_VERIFIER,
            transport=transport,
        )
    exc_text = str(excinfo.value)
    assert "POST" in exc_text
    assert "/token" in exc_text
    assert "401" in exc_text
    _assert_exception_has_no_tokens(excinfo)
    _assert_no_tokens(caplog.text)

    caplog.clear()
    with pytest.raises(AuthRevoked) as excinfo:
        refresh_access_token(
            client_id=FAKE_CLIENT_ID,
            client_secret=FAKE_CLIENT_SECRET,
            refresh_token=FAKE_REFRESH_TOKEN,
            transport=transport,
        )
    exc_text = str(excinfo.value)
    assert "POST" in exc_text
    assert "/token" in exc_text
    assert "401" in exc_text
    _assert_exception_has_no_tokens(excinfo)
    _assert_no_tokens(caplog.text)
