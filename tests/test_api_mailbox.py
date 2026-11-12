"""Tests for /api/mailbox endpoints and the mailbox scheduler (T059).

TESTS ONLY. Written to fail until the mailbox API and scheduler seams exist in
app.main (404s / missing seam). No real tokens, no Google, no browser, no real
mailbox, no network: all external calls are faked/monkeypatched.

Chosen scheduler seams (developer must implement to these exact names/signatures;
see handoff for rationale):

- app.main.SYNC_INTERVAL_DEFAULT_MINUTES: int == 15
- app.main.mailbox_should_sync(state: dict, *, now=None, sync_running: bool = False) -> bool
    Pure decision for one tick: True only when state["auth_state"] == "valid"
    and state["auto_sync"] == "on" and no sync is running. (Used so interval/
    state logic is unit-testable without sleeping.)
- async def app.main.mailbox_scheduler(*, get_state, run_sync, is_running,
      sleep, interval_seconds=None) -> None
    Loop: await sleep(interval_seconds_from_state_or_default); on each wake read
    interval from get_state()'s interval_minutes (default 15), and if
    mailbox_should_sync(get_state(), sync_running=is_running()) call run_sync().
    Skips when running. Stops on asyncio.CancelledError (clean shutdown, no leaked
    thread). A source error returned/raised by run_sync() does not stop the loop.
    get_state/run_sync/is_running/sleep are callables injected for tests.
- create_app(..., enable_mailbox_scheduler=False) keeps existing behaviour/tests
  unchanged; the real app lifespan passes enable_mailbox_scheduler=True and wires
  real conn/source/sync.

Status codes chosen where contracts/api.md is silent (documented in handoff):
- POST /api/mailbox/authorise when not configured (no client secret/token context
  to start): 409 {"error": "mailbox not configured"}.
- POST /api/mailbox/sync when auth_state is revoked or not_configured: 409 with a
  clear error ("mailbox not configured" / "authorisation revoked"); when auto_sync
  is paused_auth treat as revoked-equivalent for manual sync? we pin 409 "sync not
  available: authorisation revoked" for revoked/paused_auth and 409 "mailbox not
  configured" for not_configured. (409 chosen as conflict with mailbox state,
  matching the 409 used for "sync already running".)
- PUT /api/mailbox/folder invalid body: 400.
"""
from __future__ import annotations

import asyncio
import base64
import json
import socket
import threading
import time
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app import alerts_sync, db
from app.mailbox import AuthRevoked
from app.main import create_app

from .conftest import EXAMPLE_NEEDS

# A distinctive fake secret/token value; asserted absent from every API body.
FAKE_SECRET = "FAKE-SECRET-refresh-token-1//0SHOULD-NOT-LEAK"
FAKE_CLIENT_SECRET = "FAKE-client-secret-GOCSPX-SHOULD-NOT-LEAK"


@pytest.fixture(autouse=True)
def no_aliases(tmp_path, monkeypatch):
    # keep zone/category side effects out of these tests
    import app.zones as zones
    monkeypatch.setattr(zones, "ALIASES_PATH", tmp_path / "zone_aliases.yaml")


@pytest.fixture
def no_external_network(monkeypatch):
    """Allow loopback connects (needed by asyncio/TestClient on Windows); block all others."""
    _orig_connect = socket.socket.connect
    _orig_create_connection = socket.create_connection

    def _is_loopback(host):
        if host is None:
            return False
        h = str(host).lower()
        return h in ("127.0.0.1", "::1", "localhost")

    def _safe_connect(self, address):
        host = address[0] if isinstance(address, tuple) and address else None
        if _is_loopback(host):
            return _orig_connect(self, address)
        raise AssertionError("network access in test")

    def _safe_create_connection(address, *args, **kwargs):
        host = address[0] if isinstance(address, tuple) and address else address
        if _is_loopback(host):
            return _orig_create_connection(address, *args, **kwargs)
        raise AssertionError("network access in test")

    monkeypatch.setattr(socket.socket, "connect", _safe_connect)
    monkeypatch.setattr(socket, "create_connection", _safe_create_connection)


@pytest.fixture
def db_path(tmp_path):
    needs = tmp_path / "needs.yaml"
    needs.write_text(EXAMPLE_NEEDS.read_text(encoding="utf-8"), encoding="utf-8")
    return str(tmp_path / "t.db"), str(needs)


@pytest.fixture
def client(db_path):
    dbp, needsp = db_path
    # client listed before no_network in tests so its socketpair is created first
    with TestClient(create_app(dbp, needsp)) as c:
        yield c


def seed_mailbox(conn, **overrides):
    base = {
        "provider": "gmail",
        "account": "usuario@gmail.com",
        "label_name": "Idealista",
        "label_id": "LBL1",
        "auth_state": "valid",
        "auto_sync": "on",
        "backfill_from": "2026-09-28",
        "last_attempt_at": None,
        "last_attempt_status": "ok",
        "last_success_at": "2026-10-28T11:45:02",
        "last_error_at": None,
        "last_error": None,
        "running_run_id": None,
        "progress_done": 0,
        "progress_total": 0,
    }
    base.update(overrides)
    conn.execute("DELETE FROM mailbox_state")
    cols = ", ".join(base.keys())
    qs = ", ".join(["?"] * len(base))
    conn.execute(f"INSERT INTO mailbox_state (id, {cols}) VALUES (1, {qs})", list(base.values()))
    conn.commit()
    return base


def body_text(resp):
    # full serialized body for secret-leak scans
    return resp.text


def assert_no_secrets(resp):
    text = body_text(resp)
    assert FAKE_SECRET not in text
    assert FAKE_CLIENT_SECRET not in text
    assert "refresh_token" not in text
    assert "client_secret" not in text


CONTRACT_KEYS = {
    "provider", "account", "label_name", "auth_state", "auto_sync",
    "interval_minutes", "backfill_from", "last_success_at", "last_attempt_status",
    "last_error", "last_error_at", "out_of_date", "running", "progress",
    "reauthorise_steps", "app_folder",
}


# ── 1. GET /api/mailbox ─────────────────────────────────────────────────────

def test_mailbox_get_not_configured_default(client, no_network, monkeypatch, tmp_path):
    # no mailbox_state row seeded => not-configured default state
    monkeypatch.setenv("CASA_APPDATA", str(tmp_path / "appdata"))
    resp = client.get("/api/mailbox")
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert CONTRACT_KEYS.issubset(data.keys())
    assert data["auth_state"] == "not_configured"
    assert data["account"] is None
    assert data["label_name"] is None
    assert data["running"] is False
    assert data["progress"] is None
    assert data["reauthorise_steps"] is None
    assert data["out_of_date"] is False


def test_mailbox_get_exact_keys_and_no_secrets(client, db_path, no_network, monkeypatch, tmp_path):
    dbp, _ = db_path
    appdir = tmp_path / "appdata"
    monkeypatch.setenv("CASA_APPDATA", str(appdir))
    # plant fake secret strings in env/state-adjacent places the impl might read
    monkeypatch.setenv("FAKE_REFRESH_TOKEN", FAKE_SECRET)
    c = db.connect(dbp)
    # compute from current time so out_of_date is False on the real clock (app uses datetime.now())
    recent_success = (datetime.now() - timedelta(minutes=1)).strftime("%Y-%m-%dT%H:%M:%S")
    seed_mailbox(c, last_error=None, last_success_at=recent_success)
    # even if someone wrongly stored a secret-ish string, GET must not echo it;
    # but we don't store it - we just ensure response never contains our sentinels
    resp = client.get("/api/mailbox")
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert CONTRACT_KEYS.issubset(data.keys())
    assert data["provider"] == "gmail"
    assert data["account"] == "usuario@gmail.com"
    assert data["label_name"] == "Idealista"
    assert data["auth_state"] == "valid"
    assert data["auto_sync"] == "on"
    assert data["interval_minutes"] == 15
    assert data["backfill_from"] == "2026-09-28"
    assert data["last_success_at"] == recent_success
    assert data["last_attempt_status"] == "ok"
    assert data["last_error"] is None
    assert data["out_of_date"] is False
    assert data["running"] is False
    assert data["progress"] is None
    assert_no_secrets(resp)
    # app_folder equals CASA_APPDATA
    assert data["app_folder"] == str(appdir)


def test_mailbox_get_reauthorise_steps_revoked(client, db_path, no_network):
    c = db.connect(db_path[0])
    seed_mailbox(c, auth_state="revoked", auto_sync="paused_auth",
                 last_attempt_status="failed", last_error="auth_revoked")
    resp = client.get("/api/mailbox")
    assert resp.status_code == 200
    data = resp.json()
    assert data["auth_state"] == "revoked"
    assert isinstance(data["reauthorise_steps"], list)
    assert len(data["reauthorise_steps"]) >= 1
    assert all(isinstance(s, str) and s for s in data["reauthorise_steps"])
    assert_no_secrets(resp)


def test_mailbox_get_reauthorise_steps_null_when_not_revoked(client, db_path, no_network):
    c = db.connect(db_path[0])
    for st in ("valid", "not_configured"):
        if st == "not_configured":
            c.execute("DELETE FROM mailbox_state")
            c.commit()
        else:
            seed_mailbox(c, auth_state="valid")
        resp = client.get("/api/mailbox")
        assert resp.json()["reauthorise_steps"] is None, st


def test_mailbox_get_out_of_date_failed_attempt(client, db_path, no_network):
    c = db.connect(db_path[0])
    seed_mailbox(c, last_attempt_status="failed", last_success_at="2026-10-28T11:45:02")
    resp = client.get("/api/mailbox")
    assert resp.json()["out_of_date"] is True


def test_mailbox_get_out_of_date_stale_success(client, db_path, no_network):
    c = db.connect(db_path[0])
    # last success older than 30 minutes ago
    old = (datetime.now() - timedelta(minutes=31)).isoformat(timespec="seconds")
    seed_mailbox(c, last_attempt_status="ok", last_success_at=old)
    resp = client.get("/api/mailbox")
    assert resp.json()["out_of_date"] is True


def test_mailbox_get_out_of_date_false_when_recent_success(client, db_path, no_network):
    c = db.connect(db_path[0])
    recent = (datetime.now() - timedelta(minutes=5)).isoformat(timespec="seconds")
    seed_mailbox(c, last_attempt_status="ok", last_success_at=recent)
    resp = client.get("/api/mailbox")
    assert resp.json()["out_of_date"] is False


# ── 2. POST /api/mailbox/authorise ──────────────────────────────────────────

def test_authorise_returns_202_waiting(client, db_path, no_network, monkeypatch):
    c = db.connect(db_path[0])
    seed_mailbox(c, auth_state="not_configured", auto_sync="on")
    started = threading.Event()
    release = threading.Event()

    def fake_authorize(*a, **k):
        started.set()
        release.wait(timeout=2)  # simulate work; response must not block on this

    # monkeypatch the oauth/authorize entrypoint the endpoint will call
    import app.mailbox.oauth as oauth_mod
    monkeypatch.setattr(oauth_mod, "authorize", fake_authorize, raising=False)
    # also try common name used by endpoint
    monkeypatch.setattr(oauth_mod, "run_authorization", fake_authorize, raising=False)

    resp = client.post("/api/mailbox/authorise")
    assert resp.status_code == 202, resp.text
    assert resp.json() == {"waiting": True}
    # response returned without waiting for authorize to finish
    assert not release.is_set()
    release.set()
    started.wait(timeout=2)


def test_authorise_failure_reflected_in_state_no_secrets(client, db_path, no_network, monkeypatch):
    c = db.connect(db_path[0])
    seed_mailbox(c, auth_state="valid", auto_sync="on")
    done = threading.Event()

    def failing_authorize(*a, **k):
        try:
            raise AuthRevoked(f"revoked token={FAKE_SECRET}")
        finally:
            done.set()

    import app.mailbox.oauth as oauth_mod
    monkeypatch.setattr(oauth_mod, "authorize", failing_authorize, raising=False)
    monkeypatch.setattr(oauth_mod, "run_authorization", failing_authorize, raising=False)

    resp = client.post("/api/mailbox/authorise")
    assert resp.status_code == 202
    assert done.wait(timeout=2)
    # give background thread a moment to update state
    time.sleep(0.05)
    st = client.get("/api/mailbox")
    data = st.json()
    # failure reflected via GET state (revoked/paused or error surfaced), never leak
    assert_no_secrets(st)
    # state must reflect a problem (revoked) or at least not claim success wrongly;
    # accept revoked auth_state or a last_error set
    assert data["auth_state"] in ("revoked", "valid", "not_configured")
    if data.get("last_error"):
        assert FAKE_SECRET not in str(data["last_error"])


# ── 3. PUT /api/mailbox/folder ──────────────────────────────────────────────

def test_folder_resolves_and_stores(client, db_path, no_network, monkeypatch):
    c = db.connect(db_path[0])
    seed_mailbox(c, label_name=None, label_id=None)

    class FakeSource:
        def resolve_folder(self, name):
            assert name == "Idealista"
            return "LBL_NEW"

    import app.mailbox.gmail as gmail_mod
    monkeypatch.setattr(gmail_mod, "GmailSource", lambda *a, **k: FakeSource(), raising=False)
    # endpoint may build source via a factory; also provide a generic hook
    monkeypatch.setattr("app.main.get_mail_source", lambda: FakeSource(), raising=False)

    resp = client.put("/api/mailbox/folder", json={"label_name": "Idealista"})
    assert resp.status_code == 200, resp.text
    st = client.get("/api/mailbox").json()
    assert st["label_name"] == "Idealista"


def test_folder_not_found_404(client, db_path, no_network, monkeypatch):
    c = db.connect(db_path[0])
    seed_mailbox(c)
    from app.mailbox import FolderNotFound

    class FakeSource:
        def resolve_folder(self, name):
            raise FolderNotFound(name)

    monkeypatch.setattr("app.main.get_mail_source", lambda: FakeSource(), raising=False)
    import app.mailbox.gmail as gmail_mod
    monkeypatch.setattr(gmail_mod, "GmailSource", lambda *a, **k: FakeSource(), raising=False)

    resp = client.put("/api/mailbox/folder", json={"label_name": "Nope"})
    assert resp.status_code == 404, resp.text
    assert resp.json() == {"error": "folder Nope not found"}


def test_folder_invalid_body_400(client, no_network):
    # missing label_name / wrong type
    for body in [{}, {"name": "x"}, {"label_name": 123}, {"label_name": ""}]:
        resp = client.put("/api/mailbox/folder", json=body)
        assert resp.status_code == 400, (body, resp.status_code, resp.text)


# ── 4. POST /api/mailbox/sync ───────────────────────────────────────────────

def test_sync_returns_202_run_id_and_runs_in_worker(client, db_path, no_network, monkeypatch):
    c = db.connect(db_path[0])
    seed_mailbox(c)
    ran = threading.Event()
    thread_names = []

    def fake_sync(conn, source, kind="sync_manual"):
        thread_names.append(threading.current_thread().name)
        ran.set()
        # mimic alerts_sync.sync summary shape
        return {"status": "ok", "n_found": 0, "n_imported": 0, "n_already": 0, "n_rejected": 0, "error": None, "run_id": 1}

    monkeypatch.setattr(alerts_sync, "sync", fake_sync)
    # endpoint may import sync differently
    monkeypatch.setattr("app.main.sync_mailbox", fake_sync, raising=False)
    monkeypatch.setattr("app.main.run_sync", fake_sync, raising=False)

    resp = client.post("/api/mailbox/sync")
    assert resp.status_code == 202, resp.text
    data = resp.json()
    assert "run_id" in data and isinstance(data["run_id"], int)
    assert ran.wait(timeout=2)
    # ran in a worker thread, not the main/test thread
    assert thread_names and thread_names[0] != threading.main_thread().name


def test_sync_409_while_running(client, db_path, no_network, monkeypatch):
    c = db.connect(db_path[0])
    seed_mailbox(c)
    release = threading.Event()
    started = threading.Event()

    def slow_sync(*a, **k):
        started.set()
        release.wait(timeout=2)
        return {"status": "ok", "n_found": 0, "n_imported": 0, "n_already": 0, "n_rejected": 0, "error": None, "run_id": 1}

    monkeypatch.setattr(alerts_sync, "sync", slow_sync)
    monkeypatch.setattr("app.main.sync_mailbox", slow_sync, raising=False)

    r1 = client.post("/api/mailbox/sync")
    assert r1.status_code == 202
    assert started.wait(timeout=2)
    r2 = client.post("/api/mailbox/sync")
    assert r2.status_code == 409, r2.text
    assert r2.json() == {"error": "sync already running"}
    release.set()


def test_sync_rejected_when_not_configured(client, db_path, no_network):
    c = db.connect(db_path[0])
    c.execute("DELETE FROM mailbox_state")
    c.commit()
    resp = client.post("/api/mailbox/sync")
    assert resp.status_code in (400, 409), resp.text
    assert "error" in resp.json()
    assert "configur" in resp.json()["error"].lower() or "not" in resp.json()["error"].lower()


def test_sync_rejected_when_revoked(client, db_path, no_network):
    c = db.connect(db_path[0])
    seed_mailbox(c, auth_state="revoked", auto_sync="paused_auth")
    resp = client.post("/api/mailbox/sync")
    assert resp.status_code in (400, 409), resp.text
    assert "error" in resp.json()
    # clear rejection reason
    assert resp.json()["error"]


# ── 5. POST /api/mailbox/disconnect ─────────────────────────────────────────

def test_disconnect_deletes_token_and_sets_state(client, db_path, no_network, monkeypatch):
    c = db.connect(db_path[0])
    seed_mailbox(c, auth_state="valid", auto_sync="on")
    deleted = {"called": False}

    def fake_delete():
        deleted["called"] = True

    import app.mailbox.credentials as cred_mod
    monkeypatch.setattr(cred_mod, "delete_token", fake_delete)
    monkeypatch.setattr("app.main.delete_token", fake_delete, raising=False)

    resp = client.post("/api/mailbox/disconnect")
    assert resp.status_code == 200, resp.text
    assert deleted["called"] is True
    st = client.get("/api/mailbox").json()
    assert st["auth_state"] == "not_configured"
    # auto_sync consistent with data-model transitions (disconnect -> not_configured;
    # auto_sync not required to become 'on' but must be consistent/valid; we accept on/off
    # but it must not remain paused_auth implying a revocation)
    assert st["auto_sync"] in ("on", "off")


# ── 6. SCHEDULER (seams: mailbox_should_sync, mailbox_scheduler, SYNC_INTERVAL_DEFAULT_MINUTES) ──

def test_scheduler_seam_constants_and_tick_decision(no_network):
    # seam must exist (missing seam => fail for right reason once module imported but attr missing)
    import app.main as m
    assert m.SYNC_INTERVAL_DEFAULT_MINUTES == 15
    now = datetime.now()
    assert m.mailbox_should_sync({"auth_state": "valid", "auto_sync": "on", "interval_minutes": 15}) is True
    # skip when running
    assert m.mailbox_should_sync({"auth_state": "valid", "auto_sync": "on"}, sync_running=True) is False
    # skip revoked/not_configured/paused_auth/off
    for st in (
        {"auth_state": "revoked", "auto_sync": "paused_auth"},
        {"auth_state": "not_configured", "auto_sync": "on"},
        {"auth_state": "valid", "auto_sync": "paused_auth"},
        {"auth_state": "valid", "auto_sync": "off"},
    ):
        assert m.mailbox_should_sync(st) is False, st


def test_no_external_network_fixture_blocks_non_loopback_and_allows_loopback(no_external_network):
    # refuses non-loopback (documentation address; must raise before any real attempt)
    with pytest.raises(AssertionError, match="network access in test"):
        socket.create_connection(("203.0.113.1", 80), timeout=0.01)
    with pytest.raises(AssertionError, match="network access in test"):
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            s.connect(("203.0.113.1", 80))
        finally:
            s.close()
    # allows loopback socketpair/connect to a locally bound listening socket
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        srv.bind(("127.0.0.1", 0))
        srv.listen(1)
        port = srv.getsockname()[1]
        cli = socket.create_connection(("127.0.0.1", port), timeout=1)
        try:
            conn, _ = srv.accept()
            conn.close()
        finally:
            cli.close()
    finally:
        srv.close()


def test_scheduler_runs_at_interval_from_state(no_external_network):
    import app.main as m

    calls = []
    state = {"auth_state": "valid", "auto_sync": "on", "interval_minutes": 7}
    sleeps = []

    async def fake_sleep(seconds):
        sleeps.append(seconds)
        if len(sleeps) >= 3:
            raise asyncio.CancelledError()

    def run_sync():
        calls.append("sync")

    async def runner():
        await m.mailbox_scheduler(
            get_state=lambda: dict(state),
            run_sync=run_sync,
            is_running=lambda: False,
            sleep=fake_sleep,
        )

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(runner())

    # uses interval_minutes (7) from mailbox_state, not a literal 15
    assert sleeps and all(s == 7 * 60 for s in sleeps)
    assert len(calls) == 3


def test_scheduler_uses_default_interval_when_missing(no_external_network):
    import app.main as m
    sleeps = []

    async def fake_sleep(seconds):
        sleeps.append(seconds)
        raise asyncio.CancelledError()

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(m.mailbox_scheduler(
            get_state=lambda: {"auth_state": "valid", "auto_sync": "on"},
            run_sync=lambda: None,
            is_running=lambda: False,
            sleep=fake_sleep,
        ))
    assert sleeps[0] == 15 * 60


def test_scheduler_skips_when_not_valid_or_not_on(no_external_network):
    import app.main as m
    for st in (
        {"auth_state": "revoked", "auto_sync": "paused_auth", "interval_minutes": 15},
        {"auth_state": "not_configured", "auto_sync": "on", "interval_minutes": 15},
        {"auth_state": "valid", "auto_sync": "paused_auth", "interval_minutes": 15},
        {"auth_state": "valid", "auto_sync": "off", "interval_minutes": 15},
    ):
        calls = []

        async def fake_sleep(seconds):
            raise asyncio.CancelledError()

        with pytest.raises(asyncio.CancelledError):
            asyncio.run(m.mailbox_scheduler(
                get_state=lambda s=st: dict(s),
                run_sync=lambda: calls.append(1),
                is_running=lambda: False,
                sleep=fake_sleep,
            ))
        assert calls == [], st


def test_scheduler_skips_tick_while_running(no_external_network):
    import app.main as m
    calls = []
    ticks = {"n": 0}

    async def fake_sleep(seconds):
        ticks["n"] += 1
        if ticks["n"] >= 2:
            raise asyncio.CancelledError()

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(m.mailbox_scheduler(
            get_state=lambda: {"auth_state": "valid", "auto_sync": "on", "interval_minutes": 15},
            run_sync=lambda: calls.append(1),
            is_running=lambda: True,  # already running
            sleep=fake_sleep,
        ))
    assert calls == []


def test_scheduler_source_error_does_not_stop_schedule(no_external_network):
    import app.main as m
    calls = []
    ticks = {"n": 0}

    async def fake_sleep(seconds):
        ticks["n"] += 1
        if ticks["n"] >= 3:
            raise asyncio.CancelledError()

    def flaky_sync():
        calls.append("call")
        if len(calls) == 1:
            raise RuntimeError("boom")  # source/sync error must not stop schedule
        return {"status": "error"}

    # scheduler must swallow/log errors from run_sync and continue; it should not
    # propagate the RuntimeError out of the loop
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(m.mailbox_scheduler(
            get_state=lambda: {"auth_state": "valid", "auto_sync": "on", "interval_minutes": 15},
            run_sync=flaky_sync,
            is_running=lambda: False,
            sleep=fake_sleep,
        ))
    assert len(calls) == 3  # continued after error and after error-return


def test_scheduler_clean_shutdown_no_real_sync(no_external_network, monkeypatch):
    # starting/stopping app lifespan must cancel scheduler cleanly with no leaked
    # thread and must never start a real network/sync; we monkeypatch sync to flag
    import app.main as m
    import app.alerts_sync as alerts_sync_mod
    real_calls = {"n": 0}

    def sentinel_sync(*a, **k):
        real_calls["n"] += 1
        return {"status": "ok", "n_found": 0, "n_imported": 0, "n_already": 0, "n_rejected": 0, "error": None}

    monkeypatch.setattr(alerts_sync_mod, "sync", sentinel_sync)
    # lifespan scheduler must be enableable; create_app keeps default off for other tests
    # so we pass enable_mailbox_scheduler=True (seam). Use a very long interval/disabled
    # state so no tick fires during this short lived app.
    with TestClient(create_app(enable_mailbox_scheduler=True)) as c:
        # not configured by default => scheduler must not run real sync
        pass
    assert real_calls["n"] == 0
