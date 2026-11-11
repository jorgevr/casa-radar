"""Mailbox sync: offline tests with a FakeMailSource serving fixture bytes (T053, review iteration 1).

Every network attempt is refused by the no_network fixture. No real mailbox, no Google, no browser.
Imports of app.mailbox/app.alerts_sync are done inside tests/helpers so collection does not hide
individual cases behind one error when those modules are still missing (Phase 9 implementation out of scope).

Expected values are taken from the task/contract text (not from running production code): fixture count 12,
imported 11 / rejected 1 (the 2021 unsupported alert), first-sync window today-30 days (FR-027),
out-of-date after a failed attempt or 30 minutes without success (FR-028). All identifiers/bytes are local
test data; no secrets/tokens.
"""
from __future__ import annotations

import email
import email.policy
import threading
from datetime import date, datetime, timedelta

import pytest

from .conftest import EMAILS

FIXTURE_FILES = sorted(EMAILS.glob("*.eml"))
IMPORTED = 11  # 12 fixtures minus the one 2021 unsupported alert rejected by the reader
REJECTED = 1


# --- helpers (lazy imports so each test fails individually on the missing module) ---

def _mailbox_mod():
    from app import mailbox  # noqa: PLC0415
    return mailbox


def _sync_mod():
    from app import alerts_sync  # noqa: PLC0415
    return alerts_sync


def _insert_mailbox_state(conn, **overrides):
    base = {
        "provider": "gmail",
        "account": "fake@example.invalid",
        "label_name": "Alerts",
        "label_id": "Label_1",
        "auth_state": "valid",
        "auto_sync": "on",
        "backfill_from": (date.today() - timedelta(days=30)).isoformat(),
        "last_attempt_at": None,
        "last_attempt_status": None,
        "last_success_at": None,
        "last_error_at": None,
        "last_error": None,
        "running_run_id": None,
        "progress_done": 0,
        "progress_total": 0,
    }
    base.update(overrides)
    cols = ", ".join(base)
    placeholders = ", ".join("?" for _ in base)
    conn.execute(f"INSERT INTO mailbox_state({cols}) VALUES({placeholders})", list(base.values()))
    conn.commit()


def _state(conn):
    return conn.execute("SELECT * FROM mailbox_state").fetchone()


class FakeMailSource:
    """In-memory MailSource serving raw bytes."""

    def __init__(self, messages=None, label_id="Label_1", label_name="Alerts", acct="fake@example.invalid",
                 respect_after=True):
        # messages: {id: {"raw": bytes, "date": date, "label": label_id}}
        self._messages = messages or {}
        self._label_id = label_id
        self._label_name = label_name
        self._acct = acct
        self.respect_after = respect_after
        self.resolve_calls = 0
        self.list_calls = []
        self.fetch_calls = []

    def account(self):
        return self._acct

    def resolve_folder(self, name):
        self.resolve_calls += 1
        if name != self._label_name:
            raise _mailbox_mod().FolderNotFound(name)
        return self._label_id

    def list_ids(self, folder_id, after):
        self.list_calls.append((folder_id, after))
        ids = []
        for mid, m in self._messages.items():
            if m.get("label", self._label_id) != folder_id:
                continue
            if self.respect_after and not (m["date"] > after):
                continue
            ids.append(mid)
        # deterministic: by message date then id (oldest first among equal handling is unambiguous in tests)
        return iter(sorted(ids, key=lambda i: (self._messages[i]["date"], i)))

    def fetch_raw(self, folder_id, message_id):
        self.fetch_calls.append(message_id)
        msg = self._messages[message_id]
        if msg.get("label", self._label_id) != folder_id:
            raise _mailbox_mod().WrongFolder(message_id)
        return msg["raw"]


def _fixture_messages(day=None, n=None):
    day = day or (date.today() - timedelta(days=1))
    files = FIXTURE_FILES if n is None else FIXTURE_FILES[:n]
    return {f"msg{i}": {"raw": p.read_bytes(), "date": day, "label": "Label_1"}
            for i, p in enumerate(files)}


def _distinct_message(index, base_path=None):
    """Content-distinct RFC822 bytes (unique Message-ID) derived from a real fixture, in memory only."""
    base_path = base_path or FIXTURE_FILES[0]
    msg = email.message_from_bytes(base_path.read_bytes(), policy=email.policy.default)
    if "Message-ID" in msg:
        msg.replace_header("Message-ID", f"<distinct-{index}@test.invalid>")
    else:
        msg["Message-ID"] = f"<distinct-{index}@test.invalid>"
    return msg.as_bytes()


def _invoke_sync(conn, src, kind="sync_manual"):
    """Coordinator decision A: accept either a returned summary or ONLY named sync errors escaping.

    Returns (result, exc). Asserts on persisted state are done by each test.
    """
    alerts_sync = _sync_mod()
    mailbox = _mailbox_mod()
    named = (mailbox.AuthRevoked, mailbox.FolderNotFound, mailbox.SourceUnavailable)
    try:
        return alerts_sync.sync(conn, src, kind=kind), None
    except named as exc:
        return None, exc


def _contains_refusal(value):
    if value == "sync already running":
        return True
    if isinstance(value, str):
        return False
    if isinstance(value, dict):
        return any(_contains_refusal(v) for v in value.values())
    if isinstance(value, (list, tuple, set)):
        return any(_contains_refusal(v) for v in value)
    return False


@pytest.fixture
def malformed_rules(tmp_path, monkeypatch):
    from app import categories  # noqa: PLC0415
    path = tmp_path / "alert_categories.yaml"
    path.write_text("- contains: x\n  category: [broken\n", encoding="utf-8")
    monkeypatch.setattr(categories, "CATEGORIES_PATH", path)
    return path


@pytest.fixture
def count_load_rules(monkeypatch):
    from app import categories  # noqa: PLC0415
    real = categories.load_rules
    calls = {"n": 0}

    def counted():
        calls["n"] += 1
        return real()

    monkeypatch.setattr(categories, "load_rules", counted)
    return calls


# --- T053 cases ---

def test_malformed_rules_import_as_unknown_and_load_once(conn, no_network, malformed_rules, count_load_rules):
    src = FakeMailSource(_fixture_messages())
    _insert_mailbox_state(conn)

    result, exc = _invoke_sync(conn, src, kind="sync_manual")

    assert exc is None
    summary = result
    assert summary["n_found"] == 12
    assert summary["n_imported"] == IMPORTED
    assert summary["n_rejected"] == REJECTED
    assert count_load_rules["n"] == 1
    run = conn.execute("SELECT error, status FROM import_runs WHERE run_id=?", (summary["run_id"],)).fetchone()
    assert run["status"] == "ok"
    assert (run["error"] or "").startswith("ValueError: ")
    unknown = conn.execute("SELECT category FROM alert_emails WHERE outcome='imported'").fetchall()
    assert len(unknown) == IMPORTED
    assert {r["category"] for r in unknown} == {"unknown"}


def test_first_sync_uses_30_day_window_sets_backfill_and_skips_older(conn, no_network):
    today = date.today()
    recent = today - timedelta(days=5)
    old = today - timedelta(days=31)
    msgs = {
        "recent": {"raw": FIXTURE_FILES[0].read_bytes(), "date": recent, "label": "Label_1"},
        "old": {"raw": _distinct_message(999, FIXTURE_FILES[1]), "date": old, "label": "Label_1"},
    }
    # Fake ignores `after` in listing to prove sync itself must not fetch outside the 30-day window.
    src = FakeMailSource(msgs, respect_after=False)
    _insert_mailbox_state(conn, backfill_from=None)

    result, exc = _invoke_sync(conn, src, kind="sync_manual")

    assert exc is None
    assert src.list_calls, "sync must list the mailbox"
    assert src.list_calls[0][1] == today - timedelta(days=30)
    assert "old" not in src.fetch_calls
    stored = {r["mailbox_id"] for r in conn.execute("SELECT mailbox_id FROM alert_emails")}
    assert stored == {"recent"}
    st = _state(conn)
    assert st["backfill_from"] == (today - timedelta(days=30)).isoformat()


def test_second_sync_fetches_nothing_already_stored(conn, no_network):
    src = FakeMailSource(_fixture_messages())
    _insert_mailbox_state(conn)

    first, exc1 = _invoke_sync(conn, src, kind="sync_manual")
    assert exc1 is None
    assert first["n_imported"] == IMPORTED

    second, exc2 = _invoke_sync(conn, src, kind="sync_manual")

    assert exc2 is None
    assert len(src.fetch_calls) == 12  # only the first sync fetched
    # second sync must not re-fetch already-stored ids (FR-026)
    assert set(src.fetch_calls) == {f"msg{i}" for i in range(12)}


def test_new_message_imported_and_counted_only_once(conn, no_network):
    msgs = _fixture_messages()
    # First sync imports all but one content-distinct, importable fixture.
    msgs.pop("msg0")
    src = FakeMailSource(msgs)
    _insert_mailbox_state(conn)
    first, exc1 = _invoke_sync(conn, src, kind="sync_manual")
    assert exc1 is None
    before = conn.execute("SELECT COUNT(*) n FROM alert_emails").fetchone()["n"]

    src._messages["msg0"] = {"raw": FIXTURE_FILES[0].read_bytes(), "date": date.today() - timedelta(days=1),
                             "label": "Label_1"}
    second, exc2 = _invoke_sync(conn, src, kind="sync_manual")

    assert exc2 is None
    assert second["n_found"] == 1
    assert second["n_imported"] == 1
    assert second["n_already"] == 0
    after = conn.execute("SELECT COUNT(*) n FROM alert_emails").fetchone()["n"]
    assert after == before + 1


def test_same_email_file_then_mailbox_already_processed(conn, no_network):
    from app import alerts  # noqa: PLC0415
    f = FIXTURE_FILES[0]
    alerts.import_paths(conn, [f], kind="file_cli")
    src = FakeMailSource({"m1": {"raw": f.read_bytes(), "date": date.today() - timedelta(days=1), "label": "Label_1"}})
    _insert_mailbox_state(conn)

    result, exc = _invoke_sync(conn, src, kind="sync_manual")

    assert exc is None
    assert result["n_found"] == 1
    assert result["n_already"] == 1
    assert result["n_imported"] == 0


def test_interruption_after_n_keeps_them_and_resumes(conn, no_network):
    mailbox = _mailbox_mod()
    base = date.today() - timedelta(days=20)
    # Unambiguous oldest-first order: strictly increasing dates, zero-padded ids.
    msgs = {f"msg{i:02d}": {"raw": FIXTURE_FILES[i].read_bytes(), "date": base + timedelta(days=i),
                            "label": "Label_1"} for i in range(12)}
    fail_at = "msg03"  # fail when fetching the 4th; first 3 (msg00-msg02) already processed

    class InterruptingSource(FakeMailSource):
        def fetch_raw(self, folder_id, message_id):
            if message_id == fail_at:
                raise mailbox.SourceUnavailable("boom")
            return super().fetch_raw(folder_id, message_id)

    src = InterruptingSource(msgs)
    _insert_mailbox_state(conn)

    _, exc = _invoke_sync(conn, src, kind="sync_manual")

    assert isinstance(exc, mailbox.SourceUnavailable)
    st = _state(conn)
    assert st["last_attempt_status"] == "failed"
    stored = {r["mailbox_id"] for r in conn.execute("SELECT mailbox_id FROM alert_emails")}
    assert stored == {"msg00", "msg01", "msg02"}
    # process_message stores every processed email (including rejected) with its mailbox_id.
    assert conn.execute("SELECT COUNT(*) n FROM alert_emails WHERE mailbox_id IS NOT NULL").fetchone()["n"] == 3

    ok_src = FakeMailSource(msgs)
    result, exc2 = _invoke_sync(conn, ok_src, kind="sync_manual")

    assert exc2 is None
    summary = result
    assert summary["n_found"] == 9
    assert summary["n_imported"] + summary["n_rejected"] + summary["n_already"] == summary["n_found"]
    total = conn.execute("SELECT COUNT(*) n FROM alert_emails WHERE mailbox_id IS NOT NULL").fetchone()["n"]
    assert total == 12
    st2 = _state(conn)
    assert st2["last_attempt_status"] == "ok"
    assert st2["last_success_at"] is not None


def test_auth_revoked_sets_state_and_pauses(conn, no_network):
    mailbox = _mailbox_mod()

    class RevokedSource(FakeMailSource):
        def list_ids(self, folder_id, after):
            raise mailbox.AuthRevoked("invalid_grant")

    src = RevokedSource(_fixture_messages())
    _insert_mailbox_state(conn)

    _, exc = _invoke_sync(conn, src, kind="sync_manual")

    assert isinstance(exc, mailbox.AuthRevoked)
    st = _state(conn)
    assert st["auth_state"] == "revoked"
    assert st["auto_sync"] == "paused_auth"
    # Scheduler-skip predicate is T059 (app/main.py) and is not asserted here; see handoff OPEN DECISION (B).


def test_folder_not_found_reports_name_and_reads_nothing(conn, no_network):
    mailbox = _mailbox_mod()

    class MissingFolderSource(FakeMailSource):
        def resolve_folder(self, name):
            self.resolve_calls += 1
            raise mailbox.FolderNotFound(name)

    src = MissingFolderSource(_fixture_messages(), label_name="Idealista")
    _insert_mailbox_state(conn, label_name="Idealista")

    _, exc = _invoke_sync(conn, src, kind="sync_manual")

    assert isinstance(exc, mailbox.FolderNotFound)
    assert conn.execute("SELECT COUNT(*) n FROM alert_emails").fetchone()["n"] == 0
    assert src.list_calls == []
    assert src.fetch_calls == []
    st = _state(conn)
    assert st["last_error"] == "carpeta Idealista no encontrada"
    assert st["last_attempt_status"] == "failed"


def test_source_unavailable_records_error_and_schedule_continues(conn, no_network):
    mailbox = _mailbox_mod()

    class UnavailableSource(FakeMailSource):
        def list_ids(self, folder_id, after):
            self.list_calls.append((folder_id, after))
            raise mailbox.SourceUnavailable("network")

    src = UnavailableSource(_fixture_messages())
    _insert_mailbox_state(conn, auth_state="valid", auto_sync="on")

    _, exc = _invoke_sync(conn, src, kind="sync_manual")

    assert isinstance(exc, mailbox.SourceUnavailable)
    st = _state(conn)
    assert st["auth_state"] == "valid"
    assert st["auto_sync"] == "on"
    assert st["last_error"]
    assert st["last_attempt_status"] == "failed"


def test_second_concurrent_sync_refused(conn, no_network):
    started = threading.Event()
    release = threading.Event()

    class BlockingSource(FakeMailSource):
        def list_ids(self, folder_id, after):
            self.list_calls.append((folder_id, after))
            started.set()
            release.wait(timeout=5)
            return super().list_ids(folder_id, after)

    src = BlockingSource(_fixture_messages())
    _insert_mailbox_state(conn)
    results = {}

    def run_first():
        try:
            results["first"], results["first_exc"] = _invoke_sync(conn, src, kind="sync_manual")
        except Exception as exc:  # pragma: no cover - diagnostic
            results["first_unexpected"] = exc

    t = threading.Thread(target=run_first)
    t.start()
    # If alerts_sync/mailbox is missing, the thread fails immediately (ImportError): surface it as the
    # test failure (accepted "right reason") instead of timing out on `started`.
    while not started.is_set() and t.is_alive():
        t.join(timeout=0.05)
    if not started.is_set():
        t.join(timeout=1)
        exc = results.get("first_unexpected") or results.get("first_exc")
        if exc is not None:
            raise exc
        pytest.fail("first sync did not reach list_ids")
    try:
        second_result, second_exc = _invoke_sync(conn, src, kind="sync_manual")
    finally:
        release.set()
        t.join(timeout=5)

    assert results.get("first_unexpected") is None, repr(results.get("first_unexpected"))
    assert results.get("first_exc") is None
    first = results["first"]
    assert first is not None
    assert first["n_found"] == 12
    assert first["n_imported"] == IMPORTED
    assert first["n_rejected"] == REJECTED

    # T058/R6: second call returns "sync already running" (exact string) and does not raise.
    assert second_exc is None
    assert _contains_refusal(second_result), f"expected refusal string in {second_result!r}"
    # The second call must not list/fetch anything extra.
    assert len(src.list_calls) == 1
    assert len(src.fetch_calls) == 12


def test_out_of_date_after_failure_or_stale_success(conn, no_network):
    # Assumption (handoff): state is a dict-like object with 'last_attempt_status' and 'last_success_at'
    # (ISO timestamp string, naive/local, consistent with alerts._now). Boundary: exactly 30 minutes is
    # NOT out of date; older than 30 minutes is.
    alerts_sync = _sync_mod()
    now = datetime(2026, 10, 28, 12, 0, 0)

    failed = {"last_attempt_status": "failed", "last_success_at": (now - timedelta(minutes=5)).isoformat()}
    assert alerts_sync.out_of_date(failed, now) is True

    stale = {"last_attempt_status": "ok", "last_success_at": (now - timedelta(minutes=31)).isoformat()}
    assert alerts_sync.out_of_date(stale, now) is True

    fresh = {"last_attempt_status": "ok", "last_success_at": (now - timedelta(minutes=10)).isoformat()}
    assert alerts_sync.out_of_date(fresh, now) is False

    boundary_ok = {"last_attempt_status": "ok", "last_success_at": (now - timedelta(minutes=30)).isoformat()}
    assert alerts_sync.out_of_date(boundary_ok, now) is False

    boundary_stale = {"last_attempt_status": "ok",
                      "last_success_at": (now - timedelta(minutes=30, seconds=1)).isoformat()}
    assert alerts_sync.out_of_date(boundary_stale, now) is True

    # A failed attempt with a fresh success: the last attempt failed, so data is out of date.
    failed_after_fresh = {"last_attempt_status": "failed",
                          "last_success_at": (now - timedelta(minutes=5)).isoformat()}
    assert alerts_sync.out_of_date(failed_after_fresh, now) is True


@pytest.mark.slow
def test_thousand_message_backlog_under_ten_minutes(conn, no_network):
    day = date.today() - timedelta(days=2)
    msgs = {}
    for i in range(1000):
        base = FIXTURE_FILES[i % len(FIXTURE_FILES)]
        msgs[f"bulk{i:04d}"] = {"raw": _distinct_message(i, base), "date": day, "label": "Label_1"}
    src = FakeMailSource(msgs)
    _insert_mailbox_state(conn)

    t0 = datetime.now()
    result, exc = _invoke_sync(conn, src, kind="sync_manual")
    elapsed = (datetime.now() - t0).total_seconds()

    assert exc is None
    summary = result
    assert summary["n_found"] == 1000
    assert summary["n_imported"] + summary["n_already"] + summary["n_rejected"] == 1000
    assert summary.get("n_failed", 0) == 0
    assert elapsed < 600

