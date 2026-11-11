"""Tests for the Gmail MailSource client (T052).

Offline only: httpx.MockTransport, no real network. Imports are inside each test
so collection does not fail as a whole when app.mailbox.gmail is not yet
implemented; the expected failure at this stage is ModuleNotFoundError/ImportError
for the missing module.
"""
from __future__ import annotations

import base64
import datetime as dt
from urllib.parse import parse_qs, urlparse

import httpx
import pytest


ALLOWED_PATHS = {
    "/gmail/v1/users/me/profile",
    "/gmail/v1/users/me/labels",
    "/gmail/v1/users/me/messages",
}

FAKE_TOKEN = "fake-access-token-for-tests"


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _path(request: httpx.Request) -> str:
    return urlparse(str(request.url)).path


def _is_allowed(request: httpx.Request) -> bool:
    path = _path(request)
    if path in ALLOWED_PATHS:
        return True
    return path.startswith("/gmail/v1/users/me/messages/")


def _assert_only_allowed_gets(recorded):
    assert recorded, "expected at least one request"
    for req in recorded:
        assert req.method == "GET", f"non-GET request: {req.method} {req.url}"
        assert _is_allowed(req), f"request outside allowed endpoints: {req.url}"


def _make_source(transport: httpx.MockTransport):
    # Imported per test so each test fails individually while the module is missing.
    from app.mailbox.gmail import GmailSource  # noqa: WPS433 (runtime import on purpose)

    client = httpx.Client(
        transport=transport,
        base_url="https://gmail.googleapis.com/gmail/v1/",
        timeout=30.0,
    )
    # Constructor signature not fixed yet; try the most likely forms.
    try:
        return GmailSource(client=client, access_token=lambda: FAKE_TOKEN)
    except TypeError:
        try:
            return GmailSource(client, lambda: FAKE_TOKEN)
        except TypeError:
            return GmailSource(client)


def test_every_request_is_allowed_get(no_network):
    """FR-016: every recorded request is a GET to profile/labels/messages/messages/<id>."""
    recorded = []

    def handler(request: httpx.Request) -> httpx.Response:
        recorded.append(request)
        path = _path(request)
        if path.endswith("/profile"):
            return httpx.Response(200, json={"emailAddress": "user@example.com"})
        if path.endswith("/labels"):
            return httpx.Response(200, json={"labels": [{"id": "LBL1", "name": "Alerts"}]})
        if path.endswith("/messages"):
            return httpx.Response(200, json={"messages": [{"id": "m1"}]})
        if "/messages/" in path:
            return httpx.Response(
                200,
                json={"id": "m1", "labelIds": ["LBL1"], "raw": _b64url(b"raw-bytes")},
            )
        return httpx.Response(404, json={"error": "not found"})

    source = _make_source(httpx.MockTransport(handler))
    # Exercise the documented surface; tolerate methods that may not all exist yet
    # once the module is present by calling the core ones the task names.
    source.account()
    folder_id = source.resolve_folder("Alerts")
    list(source.list_ids(folder_id, dt.date(2026, 10, 1)))
    source.fetch_raw(folder_id, "m1")
    _assert_only_allowed_gets(recorded)


def test_list_ids_carries_label_and_after_and_follows_pagination(no_network):
    """List calls carry labelIds=<id> and q=after:yyyy/mm/dd>; pagination followed."""
    recorded = []

    def handler(request: httpx.Request) -> httpx.Response:
        recorded.append(request)
        path = _path(request)
        if path.endswith("/messages"):
            qs = parse_qs(urlparse(str(request.url)).query)
            token = qs.get("pageToken", [None])[0]
            if token is None:
                return httpx.Response(
                    200,
                    json={"messages": [{"id": "m1"}], "nextPageToken": "page-2"},
                )
            return httpx.Response(200, json={"messages": [{"id": "m2"}]})
        return httpx.Response(404, json={})

    source = _make_source(httpx.MockTransport(handler))
    ids = list(source.list_ids("LBL9", dt.date(2026, 9, 15)))

    assert ids == ["m1", "m2"]
    list_reqs = [r for r in recorded if _path(r).endswith("/messages")]
    assert len(list_reqs) == 2, "pagination must follow nextPageToken"
    for req in list_reqs:
        qs = parse_qs(urlparse(str(req.url)).query)
        assert qs.get("labelIds") == ["LBL9"], f"missing/wrong labelIds: {qs}"
        assert qs.get("q") == ["after:2026/09/15"], f"missing/wrong q: {qs}"
    assert parse_qs(urlparse(str(list_reqs[1].url)).query).get("pageToken") == ["page-2"]


def test_fetch_raw_base64url_decodes(no_network):
    """fetch_raw base64url-decodes the raw field."""
    raw_bytes = b"Subject: Hola\r\n\r\nBody \xff-ish-safe-bytes".replace(b"\xff", b"x")
    # Use bytes that are valid in an RFC822-ish payload; base64url handles arbitrary bytes.
    raw_bytes = b"From: a@b\r\nSubject: Test\r\n\r\nPrice 120.000 \xe2\x82\xac"

    def handler(request: httpx.Request) -> httpx.Response:
        path = _path(request)
        if "/messages/" in path:
            return httpx.Response(
                200,
                json={
                    "id": "m1",
                    "labelIds": ["LBL1", "INBOX"],
                    "raw": _b64url(raw_bytes),
                },
            )
        return httpx.Response(404, json={})

    source = _make_source(httpx.MockTransport(handler))
    result = source.fetch_raw("LBL1", "m1")
    assert result == raw_bytes


def test_fetch_raw_message_lacking_label_raises_wrong_folder(no_network):
    """A message lacking the label -> WrongFolder."""
    from app.mailbox import WrongFolder  # noqa: WPS433

    def handler(request: httpx.Request) -> httpx.Response:
        path = _path(request)
        if "/messages/" in path:
            return httpx.Response(
                200,
                json={"id": "m1", "labelIds": ["OTHER"], "raw": _b64url(b"raw")},
            )
        return httpx.Response(404, json={})

    source = _make_source(httpx.MockTransport(handler))
    with pytest.raises(WrongFolder):
        source.fetch_raw("LBL1", "m1")


@pytest.mark.parametrize(
    "response,exc",
    [
        (lambda: httpx.Response(429, json={"error": "rate limit"}), None),
        (lambda: httpx.Response(500, json={"error": "server"}), None),
        (lambda: httpx.Response(503, json={"error": "unavailable"}), None),
        (None, httpx.TimeoutException("timed out")),
    ],
)
def test_429_5xx_timeout_raise_source_unavailable(no_network, response, exc):
    """429/5xx/timeout -> SourceUnavailable."""
    from app.mailbox import SourceUnavailable  # noqa: WPS433

    def handler(request: httpx.Request) -> httpx.Response:
        if exc is not None:
            raise exc
        return response()

    source = _make_source(httpx.MockTransport(handler))
    # Trigger a request; list_ids is a simple GET path the client must implement.
    with pytest.raises(SourceUnavailable):
        list(source.list_ids("LBL1", dt.date(2026, 10, 1)))


def test_requests_spaced_at_least_100ms(no_network, monkeypatch):
    """Requests spaced >= 100 ms (patch the clock)."""
    recorded = []
    sleeps = []
    current = {"t": 1000.0}

    def handler(request: httpx.Request) -> httpx.Response:
        recorded.append((request, current["t"]))
        path = _path(request)
        if path.endswith("/messages"):
            return httpx.Response(200, json={"messages": [{"id": "m1"}]})
        if "/messages/" in path:
            return httpx.Response(
                200, json={"id": "m1", "labelIds": ["LBL1"], "raw": _b64url(b"r")}
            )
        return httpx.Response(404, json={})

    import time

    monkeypatch.setattr(time, "monotonic", lambda: current["t"])

    def fake_sleep(seconds):
        sleeps.append(seconds)
        current["t"] += seconds

    monkeypatch.setattr(time, "sleep", fake_sleep)

    source = _make_source(httpx.MockTransport(handler))
    list(source.list_ids("LBL1", dt.date(2026, 10, 1)))
    source.fetch_raw("LBL1", "m1")

    assert len(recorded) >= 2, "expected at least two requests to observe spacing"
    times = [t for _, t in recorded]
    for earlier, later in zip(times, times[1:]):
        assert later - earlier >= 0.1, (
            f"requests not spaced by >=100ms: {earlier} -> {later} (sleeps={sleeps})"
        )
