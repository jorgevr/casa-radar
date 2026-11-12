"""Tests for mailbox-setup and sync CLI commands (T060, contracts/cli.md, decisions.md T060).

TESTS ONLY. The implementation is not present yet: these tests must fail for the right
reason (missing sub-commands / missing seams), not syntax errors.

Chosen seams (module-level names in app.cli the developer must implement and tests monkeypatch):
  - SYNC_WAIT_TIMEOUT_SECONDS = 600  (named constant, default 10 minutes; --wait timeout)
  - _clock() -> datetime             (current time; faked in wait tests)
  - _sleep(seconds)                  (wait polling; faked so tests never really sleep)
  - _run_sync(conn, source, kind="sync_manual") -> dict  (default: alerts_sync.sync)
  - _make_source(conn, state) -> MailSource  (builds the configured mailbox source)
  - _authorize()                     (runs the OAuth authorisation flow; default: oauth.authorize or equivalent)
  - _stdin_is_tty(stream) -> bool    (default: stream.isatty(); faked for interactive prompt tests)
  - _run_detail(conn, run_id) -> dict  (rebuilds the run summary like the runs API: problems/notices + counts)

Secrets planted in fakes (FAKE_TOKEN/FAKE_SECRET) must appear in neither stdout nor stderr.
Offline only: no_network fixture; no real token, browser, Google call, mailbox or server.
"""
from __future__ import annotations

import io
import json
import sqlite3
from datetime import datetime, timedelta

import pytest

from app import alerts_sync, cli, db

# Planted in fakes; must never leak to stdout/stderr (requirement 5).
FAKE_TOKEN = "ya29.FAKE-ACCESS-TOKEN-SHOULD-NOT-LEAK"
FAKE_SECRET = "FAKE-CLIENT-SECRET-SHOULD-NOT-LEAK"
FAKE_REFRESH = "1//0FAKE-REFRESH-TOKEN-SHOULD-NOT-LEAK"

SUBJECT = "2026-10-20 ¡Bajada de precio en tu búsqueda!"


def _run(argv, *, stdin=None, monkeypatch=None):
    """Run cli.main with controlled stdin; return (code, out, err)."""
    if monkeypatch and stdin is not None:
        monkeypatch.setattr(cli.sys, "stdin", stdin)
    out, err = io.StringIO(), io.StringIO()
    if monkeypatch:
        monkeypatch.setattr(cli.sys, "stdout", out)
        monkeypatch.setattr(cli.sys, "stderr", err)
    code = cli.main(argv)
    return code, out.getvalue(), err.getvalue()


def _assert_no_secrets(out, err):
    blob = out + err
    for s in (FAKE_TOKEN, FAKE_SECRET, FAKE_REFRESH):
        assert s not in blob, f"secret leaked to output: {s!r}"


def _insert_run(conn, *, kind="sync_manual", status="ok", n_found=0, n_imported=0, n_already=0,
                n_rejected=0, n_failed=0, n_new_listings=0, n_updated_listings=0, n_price_changes=0,
                notes="[]", finished_at="2026-10-28T11:45:00"):
    cur = conn.execute(
        "INSERT INTO import_runs(kind, started_at, finished_at, status, n_found, n_imported, n_already, "
        "n_rejected, n_failed, n_new_listings, n_updated_listings, n_price_changes, notes) "
        "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (kind, "2026-10-28T11:40:00", finished_at, status, n_found, n_imported, n_already, n_rejected,
         n_failed, n_new_listings, n_updated_listings, n_price_changes, notes),
    )
    conn.commit()
    return cur.lastrowid


def _insert_email(conn, email_id, *, subject=SUBJECT, alert_date="2026-10-20T10:00:00",
                  outcome="failed", reason="precio de la tarjeta 640.000 ≠ \"a 645.000€\"",
                  run_id=1):
    conn.execute(
        "INSERT INTO alert_emails(email_id, content_hash, origin, sender, subject, search_name, alert_date, "
        "forwarded, alert_type, outcome, reason, reader_version, category, category_rules_matched, raw, "
        "first_run_id, last_run_id) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (email_id, "h", "mailbox", "noresponder@idealista.com", subject, "Pisos", alert_date, 0,
         "price_drop", outcome, reason, "idealista-2026.10", "flat", "[]", b"raw", run_id, run_id),
    )
    conn.commit()


def _ensure_mailbox_state(conn, **overrides):
    conn.execute("INSERT OR IGNORE INTO mailbox_state(id) VALUES(1)")
    base = {"provider": "gmail", "account": "usuario@gmail.com", "label_name": "Idealista",
            "label_id": "Label_old", "auth_state": "valid", "auto_sync": "on",
            "last_success_at": "2026-10-28T11:45:00", "last_attempt_status": "ok",
            "running_run_id": None, "progress_done": 0, "progress_total": 0}
    base.update(overrides)
    sets = ", ".join(f"{k}=?" for k in base)
    conn.execute(f"UPDATE mailbox_state SET {sets} WHERE id=1", list(base.values()))
    conn.commit()


class FakeSource:
    """Configured source returned by the _make_source seam."""
    def __init__(self, label_id="Label_12"):
        self.label_id = label_id
        self.token = FAKE_TOKEN  # must never be printed

    def account(self):
        return "usuario@gmail.com"

    def resolve_folder(self, name):
        return self.label_id

    def list_ids(self, folder_id, after):
        return iter(())

    def fetch_raw(self, folder_id, message_id):
        raise AssertionError("not used")


class FakeAuthError(Exception):
    """Carries a planted secret to prove errors are not printed raw."""
    def __str__(self):
        return f"boom {FAKE_SECRET} {FAKE_TOKEN}"


# --- mailbox-setup ---

class TestMailboxSetup:
    def _patch_common(self, monkeypatch, *, source=None, interactive=False):
        calls = {"authorize": 0, "resolve": []}
        source = source or FakeSource()

        def fake_authorize():
            calls["authorize"] += 1

        def fake_make_source(conn, state=None):
            return source

        monkeypatch.setattr(cli, "_authorize", fake_authorize)
        monkeypatch.setattr(cli, "_make_source", fake_make_source)
        monkeypatch.setattr(cli, "_stdin_is_tty", lambda s: interactive)
        return calls, source

    def test_with_label_authorises_resolves_stores_and_prints(self, monkeypatch, no_network):
        calls, source = self._patch_common(monkeypatch)
        conn = db.connect()
        _ensure_mailbox_state(conn, label_name=None, label_id=None)

        code, out, err = _run(["mailbox-setup", "--label", "Idealista"], monkeypatch=monkeypatch)

        assert code == 0
        assert calls["authorize"] == 1
        # Stored in mailbox_state.
        row = db.connect().execute("SELECT label_name, label_id FROM mailbox_state WHERE id=1").fetchone()
        assert row["label_name"] == "Idealista"
        assert row["label_id"] == "Label_12"
        # The three Spanish contract lines.
        assert "Cuenta: usuario@gmail.com" in out
        assert "Carpeta: Idealista (id Label_12)" in out
        assert "Permiso: solo lectura de Gmail, revocable en myaccount.google.com/permissions" in out
        _assert_no_secrets(out, err)

    def test_without_label_noninteractive_refuses_and_does_not_authorise(self, monkeypatch, no_network):
        calls, _ = self._patch_common(monkeypatch, interactive=False)
        conn = db.connect()
        _ensure_mailbox_state(conn, label_name="Antes", label_id="AntesId")

        code, out, err = _run(["mailbox-setup"], stdin=io.StringIO(""), monkeypatch=monkeypatch)

        assert code == 2
        assert calls["authorize"] == 0, "oauth.authorize must NOT be called without --label on non-interactive stdin"
        assert "--label" in out or "--label" in err
        assert "NOMBRE" in out or "NOMBRE" in err
        # No label guessed/stored.
        row = db.connect().execute("SELECT label_name, label_id FROM mailbox_state WHERE id=1").fetchone()
        assert row["label_name"] == "Antes"
        assert row["label_id"] == "AntesId"
        _assert_no_secrets(out, err)

    def test_without_label_interactive_prompts_and_continues(self, monkeypatch, no_network):
        calls, _ = self._patch_common(monkeypatch, interactive=True)
        conn = db.connect()
        _ensure_mailbox_state(conn, label_name=None, label_id=None)

        code, out, err = _run(["mailbox-setup"], stdin=io.StringIO("Idealista\n"), monkeypatch=monkeypatch)

        assert code == 0
        assert calls["authorize"] == 1
        row = db.connect().execute("SELECT label_name, label_id FROM mailbox_state WHERE id=1").fetchone()
        assert row["label_name"] == "Idealista"
        assert row["label_id"] == "Label_12"
        _assert_no_secrets(out, err)

    @pytest.mark.parametrize("exc_factory,spanish", [
        (lambda: __import__("app.mailbox", fromlist=["AuthRevoked"]).AuthRevoked(f"POST /token 401 {FAKE_TOKEN}"), "autoriza"),
        (lambda: __import__("app.mailbox", fromlist=["FolderNotFound"]).FolderNotFound(f"No {FAKE_SECRET}"), "carpeta"),
        (lambda: __import__("app.mailbox", fromlist=["SourceUnavailable"]).SourceUnavailable(f"net {FAKE_TOKEN}"), "disponible"),
    ])
    def test_setup_source_errors_exit_2_spanish_no_secrets(self, monkeypatch, no_network, exc_factory, spanish):
        def boom_authorize():
            raise exc_factory()

        monkeypatch.setattr(cli, "_authorize", boom_authorize)
        monkeypatch.setattr(cli, "_make_source", lambda conn, state=None: FakeSource())
        monkeypatch.setattr(cli, "_stdin_is_tty", lambda s: False)

        code, out, err = _run(["mailbox-setup", "--label", "Idealista"], monkeypatch=monkeypatch)

        assert code == 2
        assert "Traceback" not in out and "Traceback" not in err
        assert spanish.lower() in (out + err).lower()
        _assert_no_secrets(out, err)

    def test_setup_never_prints_secrets_on_success(self, monkeypatch, no_network):
        # Source/account may carry secret-like strings internally; output must stay clean.
        class LeakySource(FakeSource):
            def account(self):
                return f"usuario@gmail.com {FAKE_SECRET}"
        self._patch_common(monkeypatch, source=LeakySource())
        _ensure_mailbox_state(db.connect())

        code, out, err = _run(["mailbox-setup", "--label", "Idealista"], monkeypatch=monkeypatch)

        assert code == 0
        _assert_no_secrets(out, err)


# --- sync ---

class TestSync:
    def _patch_sync(self, monkeypatch, *, sync_result):
        calls = {"sync": 0, "source": 0}

        def fake_make_source(conn, state=None):
            calls["source"] += 1
            return FakeSource()

        def fake_run_sync(conn, source, kind="sync_manual"):
            calls["sync"] += 1
            return sync_result

        monkeypatch.setattr(cli, "_make_source", fake_make_source)
        monkeypatch.setattr(cli, "_run_sync", fake_run_sync)
        return calls

    def test_ok_no_failed_prints_summary_and_last_success_exit_0(self, monkeypatch, no_network):
        conn = db.connect()
        _ensure_mailbox_state(conn, last_success_at="2026-10-28T11:45:00")
        run_id = _insert_run(conn, n_found=31, n_imported=26, n_already=1, n_rejected=3, n_failed=0,
                             n_new_listings=12, n_updated_listings=3, n_price_changes=2)
        # Non-failing notices are fine; no failed email.
        calls = self._patch_sync(monkeypatch, sync_result={
            "status": "ok", "run_id": run_id, "n_found": 31, "n_imported": 26, "n_already": 1,
            "n_rejected": 3, "error": None, "notice": None,
        })

        code, out, err = _run(["sync"], monkeypatch=monkeypatch)

        assert code == 0
        assert calls["sync"] == 1
        assert "31 emails: 26 importados, 1 ya procesado, 3 rechazados, 0 fallidos" in out
        assert "anuncios: 12 nuevos, 3 actualizados (2 cambios de precio)" in out
        assert "Última sincronización correcta: 2026-10-28 11:45" in out or "Última sincronización correcta: 2026-10-28T11:45" in out
        _assert_no_secrets(out, err)

    def test_failed_email_in_run_exits_1_with_problem_lines(self, monkeypatch, no_network):
        conn = db.connect()
        _ensure_mailbox_state(conn)
        run_id = _insert_run(conn, n_found=1, n_failed=1)
        _insert_email(conn, "<e1@example>", run_id=run_id, outcome="failed",
                      reason="precio de la tarjeta 640.000 ≠ \"a 645.000€\"")
        self._patch_sync(monkeypatch, sync_result={
            "status": "ok", "run_id": run_id, "n_found": 1, "n_imported": 0, "n_already": 0,
            "n_rejected": 0, "error": None,
        })

        code, out, err = _run(["sync"], monkeypatch=monkeypatch)

        assert code == 1
        assert "FALLO" in out
        assert "precio de la tarjeta" in out
        _assert_no_secrets(out, err)

    @pytest.mark.parametrize("err_code,detail", [
        ("auth_revoked", "autorización revocada"),
        ("folder_not_found", "carpeta"),
        ("source_unavailable", "disponible"),
    ])
    def test_sync_status_error_exits_2_spanish_no_traceback_no_secrets(self, monkeypatch, no_network, err_code, detail):
        conn = db.connect()
        _ensure_mailbox_state(conn, last_error=f"{detail} {FAKE_SECRET}", last_error_at="2026-10-28T11:50:00",
                              last_attempt_status="failed")
        run_id = _insert_run(conn, status="failed", n_found=0)
        self._patch_sync(monkeypatch, sync_result={
            "status": "error", "run_id": run_id, "n_found": 0, "n_imported": 0, "n_already": 0,
            "n_rejected": 0, "error": err_code,
        })

        code, out, err = _run(["sync"], monkeypatch=monkeypatch)

        assert code == 2
        assert "Traceback" not in out and "Traceback" not in err
        assert detail.lower() in (out + err).lower() or "error" in (out + err).lower()
        _assert_no_secrets(out, err)

    def test_already_running_returned_by_sync_exits_3_without_second_sync(self, monkeypatch, no_network):
        conn = db.connect()
        _ensure_mailbox_state(conn)
        calls = self._patch_sync(monkeypatch, sync_result={
            "status": "already_running", "n_found": 0, "n_imported": 0, "n_already": 0, "n_rejected": 0,
            "error": None, "message": "sync already running",
        })

        code, out, err = _run(["sync"], monkeypatch=monkeypatch)

        assert code == 3
        assert calls["sync"] == 1  # attempted once, refused -> exit 3, not started a second time
        _assert_no_secrets(out, err)

    def test_running_run_id_set_exits_3_immediately_and_sync_not_started(self, monkeypatch, no_network):
        conn = db.connect()
        running = _insert_run(conn, status="running", finished_at=None)
        _ensure_mailbox_state(conn, running_run_id=running)
        calls = self._patch_sync(monkeypatch, sync_result={"status": "ok", "error": None})

        code, out, err = _run(["sync"], monkeypatch=monkeypatch)

        assert code == 3
        assert calls["sync"] == 0, "sync() must not be started when a sync is already running"
        _assert_no_secrets(out, err)

    def test_wait_polls_until_clears_then_runs_and_exits_per_result(self, monkeypatch, no_network):
        conn = db.connect()
        running = _insert_run(conn, status="running", finished_at=None)
        _ensure_mailbox_state(conn, running_run_id=running, last_success_at="2026-10-28T11:45:00")
        done_run = _insert_run(conn, n_found=2, n_imported=2, n_already=0, n_rejected=0, n_failed=0)

        # Fake clock/sleep: while polled, keep running; after a couple polls, clear it.
        t = {"now": datetime(2026, 10, 28, 12, 0, 0), "polls": 0}

        def fake_clock():
            return t["now"]

        def fake_sleep(seconds):
            t["polls"] += 1
            t["now"] += timedelta(seconds=seconds)
            if t["polls"] >= 2:
                c = db.connect()
                c.execute("UPDATE import_runs SET status='ok', finished_at=? WHERE run_id=?",
                          ("2026-10-28T12:00:01", running))
                c.execute("UPDATE mailbox_state SET running_run_id=NULL WHERE id=1")
                c.commit()

        calls = {"sync": 0}

        def fake_run_sync(c, source, kind="sync_manual"):
            calls["sync"] += 1
            return {"status": "ok", "run_id": done_run, "n_found": 2, "n_imported": 2, "n_already": 0,
                    "n_rejected": 0, "error": None}

        monkeypatch.setattr(cli, "_clock", fake_clock)
        monkeypatch.setattr(cli, "_sleep", fake_sleep)
        monkeypatch.setattr(cli, "_make_source", lambda c, s=None: FakeSource())
        monkeypatch.setattr(cli, "_run_sync", fake_run_sync)

        code, out, err = _run(["sync", "--wait"], monkeypatch=monkeypatch)

        assert code == 0
        assert t["polls"] >= 2
        assert calls["sync"] == 1
        assert "2 emails: 2 importados" in out
        _assert_no_secrets(out, err)

    def test_wait_timeout_exits_3_and_never_starts_sync(self, monkeypatch, no_network):
        conn = db.connect()
        running = _insert_run(conn, status="running", finished_at=None)
        _ensure_mailbox_state(conn, running_run_id=running)

        start = datetime(2026, 10, 28, 12, 0, 0)
        t = {"now": start}
        # Force a short timeout via the named constant so the fake clock can cross it quickly.
        monkeypatch.setattr(cli, "SYNC_WAIT_TIMEOUT_SECONDS", 5)

        def fake_clock():
            return t["now"]

        def fake_sleep(seconds):
            t["now"] += timedelta(seconds=max(seconds, 1))

        calls = {"sync": 0}
        monkeypatch.setattr(cli, "_clock", fake_clock)
        monkeypatch.setattr(cli, "_sleep", fake_sleep)
        monkeypatch.setattr(cli, "_make_source", lambda c, s=None: FakeSource())
        monkeypatch.setattr(cli, "_run_sync", lambda c, s, kind="sync_manual": calls.__setitem__("sync", calls["sync"] + 1))

        code, out, err = _run(["sync", "--wait"], monkeypatch=monkeypatch)

        assert code == 3
        assert calls["sync"] == 0, "must not start a sync after --wait timeout"
        _assert_no_secrets(out, err)

    def test_stale_running_run_id_not_running_does_not_count_as_running(self, monkeypatch, no_network):
        conn = db.connect()
        stale = _insert_run(conn, status="failed", finished_at="2026-10-28T10:00:00")
        _ensure_mailbox_state(conn, running_run_id=stale, last_success_at="2026-10-28T11:45:00")
        ok_run = _insert_run(conn, n_found=1, n_imported=1)
        calls = self._patch_sync(monkeypatch, sync_result={
            "status": "ok", "run_id": ok_run, "n_found": 1, "n_imported": 1, "n_already": 0,
            "n_rejected": 0, "error": None,
        })

        code, out, err = _run(["sync"], monkeypatch=monkeypatch)

        assert code == 0, "a stale running_run_id whose import run is not 'running' must not block sync"
        assert calls["sync"] == 1
        _assert_no_secrets(out, err)

    def test_sync_never_prints_secrets(self, monkeypatch, no_network):
        conn = db.connect()
        _ensure_mailbox_state(conn, last_error=f"oops {FAKE_TOKEN}{FAKE_SECRET}", last_attempt_status="failed")
        run_id = _insert_run(conn, status="failed")
        self._patch_sync(monkeypatch, sync_result={
            "status": "error", "run_id": run_id, "n_found": 0, "n_imported": 0, "n_already": 0,
            "n_rejected": 0, "error": "source_unavailable",
        })

        code, out, err = _run(["sync"], monkeypatch=monkeypatch)

        assert code == 2
        _assert_no_secrets(out, err)


# --- general / argparse ---

class TestGeneral:
    def test_existing_commands_and_exit_codes_unchanged(self, monkeypatch, no_network, tmp_path, capsys):
        # categories still parses and runs (same as before).
        from app import zones
        monkeypatch.setattr(zones, "ALIASES_PATH", tmp_path / "zone_aliases.yaml")
        code = cli.main(["categories"])
        out = capsys.readouterr().out
        assert code == 0
        assert "Reglas" in out

        # import-emails exit code unchanged (rejected-only -> 0).
        from email.message import EmailMessage
        msg = EmailMessage()
        msg["Subject"] = "Hola"
        msg["From"] = "x@example.com"
        msg["Date"] = "Tue, 27 Oct 2026 10:00:00 +0000"
        p = tmp_path / "x.eml"
        p.write_bytes(bytes(msg))
        code = cli.main(["import-emails", str(p)])
        assert code == 0

    def test_unknown_flags_rejected_for_new_commands(self):
        with pytest.raises(SystemExit) as exc:
            cli.main(["mailbox-setup", "--label", "X", "--bogus"])
        assert exc.value.code == 2
        with pytest.raises(SystemExit) as exc:
            cli.main(["sync", "--nope"])
        assert exc.value.code == 2

    def test_commands_appear_in_module_docstring_usage(self):
        doc = cli.__doc__ or ""
        assert "mailbox-setup" in doc
        assert "sync" in doc


# --- sync: unexpected exceptions (T060 follow-up) ---

class UnexpectedBoom(Exception):
    """Unexpected error whose message carries planted secrets."""
    def __str__(self):
        return f"kaboom {FAKE_TOKEN} {FAKE_SECRET} cuerpo del email"


class TestSyncUnexpectedErrors:
    def _assert_class_only(self, out, err):
        blob = out + err
        assert "UnexpectedBoom" in err
        assert "kaboom" not in blob
        assert "cuerpo del email" not in blob
        assert "Traceback" not in blob
        _assert_no_secrets(out, err)

    def test_run_sync_unexpected_exception_exits_2_class_name_only(self, monkeypatch, no_network):
        conn = db.connect()
        _ensure_mailbox_state(conn)
        calls = {"sync": 0}

        def fake_run_sync(c, source, kind="sync_manual"):
            calls["sync"] += 1
            raise UnexpectedBoom()

        monkeypatch.setattr(cli, "_make_source", lambda c, s=None: FakeSource())
        monkeypatch.setattr(cli, "_run_sync", fake_run_sync)

        code, out, err = _run(["sync"], monkeypatch=monkeypatch)

        assert code == 2
        assert calls["sync"] == 1
        self._assert_class_only(out, err)

    def test_make_source_unexpected_exception_exits_2_and_sync_not_called(self, monkeypatch, no_network):
        conn = db.connect()
        _ensure_mailbox_state(conn)
        calls = {"sync": 0}

        def boom_source(c, s=None):
            raise UnexpectedBoom()

        def fake_run_sync(c, source, kind="sync_manual"):
            calls["sync"] += 1
            return {}

        monkeypatch.setattr(cli, "_make_source", boom_source)
        monkeypatch.setattr(cli, "_run_sync", fake_run_sync)

        code, out, err = _run(["sync"], monkeypatch=monkeypatch)

        assert code == 2
        assert calls["sync"] == 0
        self._assert_class_only(out, err)

    def test_wait_then_unexpected_exception_exits_2_single_sync(self, monkeypatch, no_network):
        conn = db.connect()
        running = _insert_run(conn, status="running", finished_at=None)
        _ensure_mailbox_state(conn, running_run_id=running)
        t = {"now": datetime(2026, 10, 28, 12, 0, 0)}

        def fake_sleep(seconds):
            t["now"] += timedelta(seconds=seconds)
            c = db.connect()
            c.execute("UPDATE import_runs SET status='ok', finished_at=? WHERE run_id=?",
                      ("2026-10-28T12:00:01", running))
            c.execute("UPDATE mailbox_state SET running_run_id=NULL WHERE id=1")
            c.commit()

        calls = {"sync": 0}

        def fake_run_sync(c, source, kind="sync_manual"):
            calls["sync"] += 1
            raise UnexpectedBoom()

        monkeypatch.setattr(cli, "_clock", lambda: t["now"])
        monkeypatch.setattr(cli, "_sleep", fake_sleep)
        monkeypatch.setattr(cli, "_make_source", lambda c, s=None: FakeSource())
        monkeypatch.setattr(cli, "_run_sync", fake_run_sync)

        code, out, err = _run(["sync", "--wait"], monkeypatch=monkeypatch)

        assert code == 2
        assert calls["sync"] == 1
        self._assert_class_only(out, err)

    def test_keyboard_interrupt_from_run_sync_propagates(self, monkeypatch, no_network):
        conn = db.connect()
        _ensure_mailbox_state(conn)

        def fake_run_sync(c, source, kind="sync_manual"):
            raise KeyboardInterrupt()

        monkeypatch.setattr(cli, "_make_source", lambda c, s=None: FakeSource())
        monkeypatch.setattr(cli, "_run_sync", fake_run_sync)

        with pytest.raises(KeyboardInterrupt):
            _run(["sync"], monkeypatch=monkeypatch)
