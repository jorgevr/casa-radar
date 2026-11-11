"""Tests for the Gmail MailSource client (T052).

Offline only: httpx.MockTransport, no real network. Imports are inside each test
so collection does not fail as a whole when app.mailbox.gmail is not yet
implemented; the expected failure at this stage is ModuleNotFoundError/ImportError
for the missing module.
"""
from __future__ import annotations

import datetime as dt
import re
import time
from urllib.parse import parse_qs, urlparse

import httpx
import pytest


ALLOWED_PATHS = {
    "/gmail/v1/users/me/profile",
    "/gmail/v1/users/me/labels",
    "/gmail/v1/users/me/messages",
}

FAKE_TOKEN = "fake-access-token-for-tests"


def _path(request: httpx.Request) -> str:
    return urlparse(str(request.url)).path


def _is_message_item_path(path: str) -> bool:
    # Allow only /gmail/v1/users/me/messages/<id> with no further segments.
    return re.fullmatch(r"/gmail/v1/users/me/messages/[^/]+", path) is not None


def _is_allowed(request: httpx.Request) -> bool:
    path = _path(request)
    if path in ALLOWED_PATHS:
        return True
    return _is_message_item_path(path)


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
    # NEW proposed interface (not in tasks.md/contracts; pending approval before T057):
    # GmailSource(client=<httpx.Client>, access_token=<zero-arg callable -> str>), keyword-only.
    return GmailSource(client=client, access_token=lambda: FAKE_TOKEN)


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
        if path == "/gmail/v1/users/me/messages":
            return httpx.Response(200, json={"messages": [{"id": "m1"}]})
        if _is_message_item_path(path):
            # Hand-computed base64url (no padding): b"raw" = bytes 0x72,0x61,0x77
            # bits 01110010 01100001 01110111 -> 6-bit groups 011100(28='c'),
            # 100110(38='m'), 000101(5='F'), 110111(55='3') => "cmF3".
            return httpx.Response(
                200,
                json={"id": "m1", "labelIds": ["LBL1"], "raw": "cmF3"},
            )
        return httpx.Response(404, json={"error": "not found"})

    source = _make_source(httpx.MockTransport(handler))
    account = source.account()
    folder_id = source.resolve_folder("Alerts")
    ids = list(source.list_ids(folder_id, dt.date(2026, 10, 1)))
    raw = source.fetch_raw(folder_id, "m1")

    _assert_only_allowed_gets(recorded)
    paths = [_path(r) for r in recorded]
    assert any(p.endswith("/profile") for p in paths), "profile endpoint not requested"
    assert any(p.endswith("/labels") for p in paths), "labels endpoint not requested"
    assert any(p == "/gmail/v1/users/me/messages" for p in paths), "messages list not requested"
    assert any(_is_message_item_path(p) for p in paths), "message item endpoint not requested"

    assert account == "user@example.com"
    assert folder_id == "LBL1"
    assert ids == ["m1"]
    assert raw == b"raw"

    msg_reqs = [r for r in recorded if _is_message_item_path(_path(r))]
    assert msg_reqs, "expected at least one message fetch request"
    for req in msg_reqs:
        qs = parse_qs(urlparse(str(req.url)).query)
        assert qs.get("format") == ["raw"], f"message fetch must request format=raw: {qs}"


def test_list_ids_carries_label_and_after_and_follows_pagination(no_network):
    """List calls carry labelIds=<id> and q=after:yyyy/mm/dd>; pagination followed."""
    recorded = []

    def handler(request: httpx.Request) -> httpx.Response:
        recorded.append(request)
        path = _path(request)
        if path == "/gmail/v1/users/me/messages":
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
    list_reqs = [r for r in recorded if _path(r) == "/gmail/v1/users/me/messages"]
    assert len(list_reqs) == 2, "pagination must follow nextPageToken"
    for req in list_reqs:
        qs = parse_qs(urlparse(str(req.url)).query)
        assert qs.get("labelIds") == ["LBL9"], f"missing/wrong labelIds: {qs}"
        assert qs.get("q") == ["after:2026/09/15"], f"missing/wrong q: {qs}"
    assert parse_qs(urlparse(str(list_reqs[1].url)).query).get("pageToken") == ["page-2"]


def test_fetch_raw_base64url_decodes(no_network):
    """fetch_raw base64url-decodes the raw field (URL-safe alphabet, stripped padding)."""
    # Hand-computed base64url (no standard base64, no encoder-derived expected value):
    # raw bytes: 0xFB, 0xFF (2 bytes, length not multiple of 3 -> stripped padding case)
    # bits: 11111011 11111111
    # 6-bit groups: 111110 (62='-'), 111111 (63='_'), 111100 (60='8', with 2 padding bits)
    # base64url with padding would be "-_8="; Gmail omits '=' so raw field is "-_8"
    # (contains '-' and '_' and has stripped padding).
    encoded_raw = "-_8"
    expected = bytes([0xFB, 0xFF])

    def handler(request: httpx.Request) -> httpx.Response:
        path = _path(request)
        if _is_message_item_path(path):
            return httpx.Response(
                200,
                json={
                    "id": "m1",
                    "labelIds": ["LBL1", "INBOX"],
                    "raw": encoded_raw,
                },
            )
        return httpx.Response(404, json={})

    source = _make_source(httpx.MockTransport(handler))
    result = source.fetch_raw("LBL1", "m1")
    assert result == expected


def test_fetch_raw_message_lacking_label_raises_wrong_folder(no_network):
    """A message lacking the label -> WrongFolder."""
    from app.mailbox import WrongFolder  # noqa: WPS433

    def handler(request: httpx.Request) -> httpx.Response:
        path = _path(request)
        if _is_message_item_path(path):
            return httpx.Response(
                200,
                json={"id": "m1", "labelIds": ["OTHER"], "raw": "cmF3"},
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
    """429/5xx/timeout -> SourceUnavailable with no retries."""
    from app.mailbox import SourceUnavailable  # noqa: WPS433

    calls = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        if exc is not None:
            raise exc
        return response()

    source = _make_source(httpx.MockTransport(handler))
    with pytest.raises(SourceUnavailable):
        list(source.list_ids("LBL1", dt.date(2026, 10, 1)))
    assert calls["count"] == 1, f"expected exactly 1 request (no retries), got {calls['count']}"


@pytest.mark.parametrize(
    "response,exc",
    [
        (lambda: httpx.Response(500, json={"error": "server"}), None),
        (None, httpx.TimeoutException("timed out")),
    ],
)
def test_fetch_raw_5xx_timeout_raise_source_unavailable(no_network, response, exc):
    """fetch_raw 5xx/timeout -> SourceUnavailable (no retries)."""
    from app.mailbox import SourceUnavailable  # noqa: WPS433

    calls = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        if exc is not None:
            raise exc
        return response()

    source = _make_source(httpx.MockTransport(handler))
    with pytest.raises(SourceUnavailable):
        source.fetch_raw("LBL1", "m1")
    assert calls["count"] == 1, f"expected exactly 1 request (no retries), got {calls['count']}"


def test_requests_spaced_at_least_100ms(no_network, monkeypatch):
    """Requests spaced >= 100 ms using a shared fake clock (>=3 requests)."""
    recorded = []
    sleeps = []
    current = {"t": 1000.0}

    def now():
        return current["t"]

    def fake_sleep(seconds):
        sleeps.append(seconds)
        current["t"] += seconds

    # Patch all common clock primitives and sleep via module attributes so the
    # implementation must use time.* module attributes (not `from time import ...`).
    monkeypatch.setattr(time, "monotonic", now)
    monkeypatch.setattr(time, "perf_counter", now)
    monkeypatch.setattr(time, "time", now)
    monkeypatch.setattr(time, "sleep", fake_sleep)

    def handler(request: httpx.Request) -> httpx.Response:
        recorded.append((request, current["t"]))
        path = _path(request)
        if path == "/gmail/v1/users/me/messages":
            qs = parse_qs(urlparse(str(request.url)).query)
            token = qs.get("pageToken", [None])[0]
            if token is None:
                return httpx.Response(
                    200,
                    json={"messages": [{"id": "m1"}], "nextPageToken": "page-2"},
                )
            return httpx.Response(200, json={"messages": [{"id": "m2"}]})
        if _is_message_item_path(path):
            return httpx.Response(
                200, json={"id": "m1", "labelIds": ["LBL1"], "raw": "cmF3"}
            )
        return httpx.Response(404, json={})

    source = _make_source(httpx.MockTransport(handler))
    # Two list pages plus one fetch => at least 3 recorded requests and 2 gaps.
    list(source.list_ids("LBL1", dt.date(2026, 10, 1)))
    source.fetch_raw("LBL1", "m1")

    assert len(recorded) >= 3, f"expected >=3 requests (2 list pages + 1 fetch), got {len(recorded)}"
    times = [t for _, t in recorded]
    for earlier, later in zip(times, times[1:]):
        assert later - earlier >= 0.1, (
            f"requests not spaced by >=100ms: {earlier} -> {later} (sleeps={sleeps})"
        )


def _status_source(status: int, body=None):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json=body if body is not None else {"error": "x"})

    return _make_source(httpx.MockTransport(handler))


@pytest.mark.parametrize("status", [401, 403])
def test_401_403_raise_auth_revoked_without_token(no_network, caplog, status):
    """401/403 -> AuthRevoked (re-authorise); message is method/path/status only, no token."""
    from app.mailbox import AuthRevoked  # noqa: WPS433

    caplog.set_level("DEBUG")
    source = _status_source(status)
    with pytest.raises(AuthRevoked) as info:
        source.account()
    text = str(info.value)
    assert str(status) in text
    assert "users/me/profile" in text
    assert FAKE_TOKEN not in text
    assert "Bearer" not in text
    assert FAKE_TOKEN not in caplog.text


@pytest.mark.parametrize("status", [401, 403])
def test_auth_revoked_on_every_call_path(no_network, status):
    from app.mailbox import AuthRevoked  # noqa: WPS433

    source = _status_source(status)
    with pytest.raises(AuthRevoked):
        source.resolve_folder("Alerts")
    with pytest.raises(AuthRevoked):
        list(source.list_ids("LBL1", dt.date(2026, 10, 1)))
    with pytest.raises(AuthRevoked):
        source.fetch_raw("LBL1", "m1")


def test_resolve_folder_unknown_label_raises_folder_not_found(no_network):
    from app.mailbox import FolderNotFound  # noqa: WPS433

    source = _status_source(200, {"labels": [{"id": "LBL1", "name": "Alerts"}]})
    with pytest.raises(FolderNotFound):
        source.resolve_folder("Nope")


def test_404_is_source_unavailable_contract_lists_no_404(no_network):
    """contracts/mail-source.md lists no 404 mapping: 404 stays SourceUnavailable (status only)."""
    from app.mailbox import SourceUnavailable  # noqa: WPS433

    source = _status_source(404)
    with pytest.raises(SourceUnavailable) as info:
        source.fetch_raw("LBL1", "m1")
    assert "404" in str(info.value)
    assert FAKE_TOKEN not in str(info.value)
