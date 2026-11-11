"""Mailbox sync: offline tests with a FakeMailSource serving fixture bytes (T053).

Every network attempt is refused by the no_network fixture. No real mailbox, no Google, no browser.
Imports of app.mailbox/app.alerts_sync are done inside each test so collection does not hide individual
cases behind one error when those modules are still missing (Phase 9 implementation is out of scope).

Expected values are taken from the task/contract text (not from running production code): fixture count 12,
imported 11 / rejected 1 (the 2021 unsupported alert), first-sync window today-30 days (FR-027),
out-of-date after a failed attempt or 30 minutes without success (FR-028). Uses obviously fake tokens/ids.
"""
from __future__ import annotations

import threading
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest

from .conftest import EMAILS, ROOT

FIXTURE_FILES = sorted(EMAILS.glob("*.eml"))
IMPORTED = 11  # 12 fixtures minus the one 2021 unsupported alert rejected by the reader
REJECTED = 1
FAKE_TOKEN = "ya29.FAKE-REFRESH-TOKEN-NOT-REAL"
FAKE_ACCESS = "ya29.FAKE-ACCESS-TOKEN-NOT-REAL"


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
    """In-memory MailSource serving raw bytes (fixture bytes by default)."""

    def __init__(self, messages=None, label_id="Label_1", label_name="Alerts", acct="fake@example.invalid"):
        # messages: {id: {"raw": bytes, "date": date, "label": label_id}}
        self._messages = messages or {}
        self._label_id = label_id
        self._label_name = label_name
        self._acct = acct
        self.list_calls = []

    def account(self):
        return self._acct

    def resolve_folder(self, name):
        if name != self._label_name:
            raise _mailbox_mod().FolderNotFound(name)
        return self._label_id

    def list_ids(self, folder_id, after):
        self.list_calls.append((folder_id, after))
        ids = [mid for mid, m in self._messages.items()
               if m.get("label", self._label_id) == folder_id and m["date"] > after]
        return iter(sorted(ids))

    def fetch_raw(self, folder_id, message_id):
        msg = self._messages[message_id]
        if msg.get("label", self._label_id) != folder_id:
            raise _mailbox_mod().WrongFolder(message_id)
        return msg["raw"]


def _fixture_messages(day=None, n=None):
    day = day or (date.today() - timedelta(days=1))
    files = FIXTURE_FILES if n is None else FIXTURE_FILES[:n]
    return {f"msg{i}": {"raw": p.read_bytes(), "date": day, "label": "Label_1"}
            for i, p in enumerate(files)}


def _one_message(mid="msg1", day=None):
    day = day or (date.today() - timedelta(days=1))
    return {mid: {"raw": FIXTURE_FILES[0].read_bytes(), "date": day, "label": "Label_1"}}


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
    alerts_sync = _sync_mod()
    src = FakeMailSource(_fixture_messages())
    _insert_mailbox_state(conn)

    summary = alerts_sync.sync(conn, src, kind="sync_manual")

    assert summary["n_found"] == 12
    assert summary["n_imported"] == IMPORTED
    assert summary["n_rejected"] == REJECTED
    assert count_load_rules["n"] == 1
    run = conn.execute("SELECT error, status FROM import_runs WHERE run_id=?", (summary["run_id"],)).fetchone()
    assert run["status"] == "ok"
    assert (run["error"] or "").startswith("ValueError: ")
    cats = {r["category"] for r in conn.execute("SELECT category FROM alert_emails WHERE outcome='imported'")}
    assert cats == {"unknown"}


def test_first_sync_uses_30_day_window_and_skips_older(conn, no_network):
    alerts_sync = _sync_mod()
    today = date.today()
    recent = today - timedelta(days=5)
    old = today - timedelta(days=31)
    msgs = _one_message("recent", recent)
    msgs["old"] = {"raw": FIXTURE_FILES[1].read_bytes(), "date": old, "label": "Label_1"}
    src = FakeMailSource(msgs)
    _insert_mailbox_state(conn, backfill_from=(today - timedelta(days=30)).isoformat())

    summary = alerts_sync.sync(conn, src, kind="sync_manual")

    assert src.list_calls, "sync must list the mailbox"
    after = src.list_calls[0][1]
    assert after == today - timedelta(days=30)
    assert summary["n_found"] == 1
    stored = {r["mailbox_id"] for r in conn.execute("SELECT mailbox_id FROM alert_emails")}
    assert stored == {"recent"}


def test_second_sync_fetches_nothing_already_stored(conn, no_network):
    alerts_sync = _sync_mod()
    src = FakeMailSource(_fixture_messages())
    _insert_mailbox_state(conn)

    first = alerts_sync.sync(conn, src, kind="sync_manual")
    second = alerts_sync.sync(conn, src, kind="sync_manual")

    assert first["n_imported"] == IMPORTED
    assert second["n_found"] == 0
    assert second["n_imported"] == 0
    assert second["n_already"] == 0


def test_new_message_imported_and_counted_only_once(conn, no_network):
    alerts_sync = _sync_mod()
    msgs = _fixture_messages()
    src = FakeMailSource(msgs)
    _insert_mailbox_state(conn)
    alerts_sync.sync(conn, src, kind="sync_manual")

    # add one new message after first sync
    extra_day = date.today() - timedelta(days=1)
    src._messages["msg_new"] = {"raw": FIXTURE_FILES[0].read_bytes(), "date": extra_day, "label": "Label_1"}
    # same content as fixture 0 but different mailbox id: dedupe is by email_id/content identity (FR-026)
    summary = alerts_sync.sync(conn, src, kind="sync_manual")

    # it was found (new mailbox id) but must count as already processed if content/email_id matches
    assert summary["n_found"] == 1
    assert summary["n_imported"] == 0
    assert summary["n_already"] == 1


def test_same_email_file_then_mailbox_already_processed(conn, no_network):
    from app import alerts  # noqa: PLC0415
    alerts_sync = _sync_mod()
    f = FIXTURE_FILES[0]
    alerts.import_paths(conn, [f], kind="file_cli")
    src = FakeMailSource({"m1": {"raw": f.read_bytes(), "date": date.today() - timedelta(days=1), "label": "Label_1"}})
    _insert_mailbox_state(conn)

    summary = alerts_sync.sync(conn, src, kind="sync_manual")

    assert summary["n_found"] == 1
    assert summary["n_already"] == 1
    assert summary["n_imported"] == 0


def test_interruption_after_n_keeps_them_and_resumes(conn, no_network):
    alerts_sync = _sync_mod()
    mailbox = _mailbox_mod()
    msgs = _fixture_messages()
    ids = sorted(msgs)
    fail_at = ids[3]  # fail when fetching the 4th; 3 already processed

    class InterruptingSource(FakeMailSource):
        def fetch_raw(self, folder_id, message_id):
            if message_id == fail_at:
                raise mailbox.SourceUnavailable("boom")
            return super().fetch_raw(folder_id, message_id)

    src = InterruptingSource(msgs)
    _insert_mailbox_state(conn)

    with pytest.raises(mailbox.SourceUnavailable):
        alerts_sync.sync(conn, src, kind="sync_manual")

    processed = conn.execute("SELECT COUNT(*) n FROM alert_emails WHERE mailbox_id IS NOT NULL").fetchone()["n"]
    assert processed == 3

    # resume with a healthy source: previously processed skipped, rest imported
    ok_src = FakeMailSource(msgs)
    summary = alerts_sync.sync(conn, ok_src, kind="sync_manual")
    assert summary["n_found"] == 9
    total = conn.execute("SELECT COUNT(*) n FROM alert_emails WHERE mailbox_id IS NOT NULL").fetchone()["n"]
    assert total == 12


def test_auth_revoked_sets_state_and_pauses(conn, no_network):
    alerts_sync = _sync_mod()
    mailbox = _mailbox_mod()

    class RevokedSource(FakeMailSource):
        def list_ids(self, folder_id, after):
            raise mailbox.AuthRevoked("invalid_grant")

    src = RevokedSource(_fixture_messages())
    _insert_mailbox_state(conn)

    with pytest.raises(mailbox.AuthRevoked):
        alerts_sync.sync(conn, src, kind="sync_manual")

    st = _state(conn)
    assert st["auth_state"] == "revoked"
    assert st["auto_sync"] == "paused_auth"


def test_auth_revoked_scheduler_skips(conn, no_network):
    alerts_sync = _sync_mod()

    class CountingSource(FakeMailSource):
        def __init__(self):
            super().__init__(_fixture_messages())
            self.listed = 0

        def list_ids(self, folder_id, after):
            self.listed += 1
            return super().list_ids(folder_id, after)

    src = CountingSource()
    _insert_mailbox_state(conn, auth_state="revoked", auto_sync="paused_auth")

    summary = alerts_sync.sync(conn, src, kind="sync_scheduled")

    assert src.listed == 0
    assert summary["n_found"] == 0


def test_folder_not_found_reports_name_and_reads_nothing(conn, no_network):
    alerts_sync = _sync_mod()
    mailbox = _mailbox_mod()

    class MissingFolderSource(FakeMailSource):
        def resolve_folder(self, name):
            raise mailbox.FolderNotFound(name)

    src = MissingFolderSource(_fixture_messages(), label_name="Idealista")
    _insert_mailbox_state(conn, label_name="Idealista")

    with pytest.raises(mailbox.FolderNotFound):
        alerts_sync.sync(conn, src, kind="sync_manual")

    assert conn.execute("SELECT COUNT(*) n FROM alert_emails").fetchone()["n"] == 0
    st = _state(conn)
    err = st["last_error"] or ""
    assert "carpeta" in err and "Idealista" in err


def test_source_unavailable_records_error_and_schedule_continues(conn, no_network):
    alerts_sync = _sync_mod()
    mailbox = _mailbox_mod()

    class UnavailableSource(FakeMailSource):
        def list_ids(self, folder_id, after):
            raise mailbox.SourceUnavailable("network")

    src = UnavailableSource(_fixture_messages())
    _insert_mailbox_state(conn, auth_state="valid", auto_sync="on")

    with pytest.raises(mailbox.SourceUnavailable):
        alerts_sync.sync(conn, src, kind="sync_scheduled")

    st = _state(conn)
    assert st["auth_state"] == "valid"
    assert st["auto_sync"] == "on"
    assert st["last_error"]
    assert st["last_attempt_status"] == "failed"


def test_second_concurrent_sync_refused(conn, no_network):
    alerts_sync = _sync_mod()
    started = threading.Event()
    release = threading.Event()

    class BlockingSource(FakeMailSource):
        def list_ids(self, folder_id, after):
            started.set()
            release.wait(timeout=5)
            return super().list_ids(folder_id, after)

    src = BlockingSource(_fixture_messages())
    _insert_mailbox_state(conn)
    results = {}

    def run_first():
        try:
            results["first"] = alerts_sync.sync(conn, src, kind="sync_manual")
        except Exception as exc:  # pragma: no cover - diagnostic
            results["first_exc"] = exc

    t = threading.Thread(target=run_first)
    t.start()
    assert started.wait(timeout=5)
    try:
        with pytest.raises(Exception) as excinfo:
            alerts_sync.sync(conn, src, kind="sync_manual")
        msg = str(excinfo.value).lower()
        assert "sync" in msg and ("running" in msg or "ejec" in msg or "progreso" in msg)
    finally:
        release.set()
        t.join(timeout=5)
    assert "first_exc" not in results


def test_out_of_date_after_failure_or_stale_success(conn, no_network):
    alerts_sync = _sync_mod()
    now = datetime.now()

    failed = {"last_attempt_status": "failed", "last_success_at": (now - timedelta(minutes=5)).isoformat()}
    assert alerts_sync.out_of_date(failed, now) is True

    stale = {"last_attempt_status": "ok", "last_success_at": (now - timedelta(minutes=31)).isoformat()}
    assert alerts_sync.out_of_date(stale, now) is True

    fresh = {"last_attempt_status": "ok", "last_success_at": (now - timedelta(minutes=10)).isoformat()}
    assert alerts_sync.out_of_date(fresh, now) is False


@pytest.mark.slow
def test_thousand_message_backlog_under_ten_minutes(conn, no_network):
    alerts_sync = _sync_mod()
    base = _fixture_messages()
    base_ids = list(base)
    msgs = {}
    day = date.today() - timedelta(days=2)
    for i in range(1000):
        src_id = base_ids[i % len(base_ids)]
        msgs[f"bulk{i}"] = {"raw": base[src_id]["raw"], "date": day, "label": "Label_1"}
    src = FakeMailSource(msgs)
    _insert_mailbox_state(conn)

    t0 = datetime.now()
    summary = alerts_sync.sync(conn, src, kind="sync_manual")
    elapsed = (datetime.now() - t0).total_seconds()

    assert summary["n_found"] == 1000
    assert elapsed < 600
