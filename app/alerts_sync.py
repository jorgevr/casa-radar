"""Mailbox sync: list a folder, import each new message in its own transaction, keep progress in mailbox_state.

Contract: specs/001-alert-email-import/contracts/mail-source.md; research R5 (window, overlap) and R6 (lock,
failure states). Source errors (AuthRevoked, FolderNotFound, SourceUnavailable) never escape: they are mapped to
mailbox_state and returned in the summary. Any other exception, including BaseException subclasses such as
KeyboardInterrupt, finalises the run and mailbox_state as failed, releases the lock and is re-raised.
Errors carry short codes only, never message text, tokens or paths.
"""
from __future__ import annotations

import threading
from datetime import date, datetime, timedelta

from . import alerts, categories
from .mailbox import AuthRevoked, FolderNotFound, SourceUnavailable, WrongFolder

FIRST_SYNC_DAYS = 30        # FR-027: first sync looks back 30 days
OVERLAP_DAYS = 2            # R5: clock skew and late delivery
STALE_AFTER = timedelta(minutes=30)  # FR-028: two 15-minute intervals

REFUSED = "sync already running"
_LOCK = threading.Lock()

_STATE_FIELDS = ("provider", "account", "label_name", "label_id", "auth_state", "auto_sync", "backfill_from",
                 "last_attempt_at", "last_attempt_status", "last_success_at", "last_error_at", "last_error",
                 "running_run_id", "progress_done", "progress_total")


def _now() -> datetime:
    return datetime.now()


def read_state(conn) -> dict | None:
    row = conn.execute("SELECT * FROM mailbox_state WHERE id=1").fetchone()
    return dict(row) if row else None


def write_state(conn, **fields) -> None:
    """Update the single mailbox_state row; only known columns are accepted."""
    unknown = set(fields) - set(_STATE_FIELDS)
    if unknown:
        raise ValueError(f"unknown mailbox_state fields: {', '.join(sorted(unknown))}")
    if not fields:
        return
    sets = ", ".join(f"{k}=?" for k in fields)
    conn.execute(f"UPDATE mailbox_state SET {sets} WHERE id=1", list(fields.values()))
    conn.commit()


def out_of_date(state, now: datetime) -> bool:
    """True when the last attempt failed or the last success is more than 30 minutes old (or missing)."""
    if state is None:
        return False
    if state["last_attempt_status"] == "failed":
        return True
    last = state["last_success_at"]
    if not last:
        return state["last_attempt_status"] is not None
    return now - datetime.fromisoformat(last) > STALE_AFTER


def _summary(status: str, error: str | None = None, **counts) -> dict:
    out = {"status": status, "n_found": 0, "n_imported": 0, "n_already": 0, "n_rejected": 0, "error": error}
    out.update(counts)
    return out


def _window_start(state: dict, today: date) -> date:
    """First sync: today - 30 days; later syncs: last success date - 2 days (not clamped to backfill_from)."""
    last = state["last_success_at"]
    if last:
        return datetime.fromisoformat(last).date() - timedelta(days=OVERLAP_DAYS)
    return today - timedelta(days=FIRST_SYNC_DAYS)


def sync(conn, source, kind: str = "sync_manual") -> dict:
    """Run one mailbox sync and return its summary; never raises for source errors (other exceptions re-raise)."""
    if not _LOCK.acquire(blocking=False):
        return _summary("already_running", message=REFUSED)
    try:
        return _run(conn, source, kind)
    finally:
        _LOCK.release()


def _run(conn, source, kind: str) -> dict:
    state = read_state(conn)
    if state is None:
        raise RuntimeError("mailbox is not configured")  # misconfiguration, not a source error
    now = _now()
    today = now.date()
    after = _window_start(state, today)
    run_id = alerts.start_run(conn, kind)
    write_state(conn, last_attempt_at=now.isoformat(timespec="seconds"), running_run_id=run_id,
                progress_done=0, progress_total=0)
    if not state["backfill_from"]:
        write_state(conn, backfill_from=(today - timedelta(days=FIRST_SYNC_DAYS)).isoformat())

    error: str | None = None       # short code returned to the caller
    detail: str | None = None      # reason stored in mailbox_state.last_error
    run_error: str | None = None
    notice = None
    try:
        try:
            rules = categories.load_rules()
        except ValueError as exc:  # malformed rules must not lose emails: store as 'unknown', report it
            rules, run_error = [], f"ValueError: {exc}"
        label = state["label_name"]
        folder_id = source.resolve_folder(label)
        if state["label_id"] and state["label_id"] != folder_id:
            notice = "folder identity changed"
        write_state(conn, label_id=folder_id)
        known = {r[0] for r in conn.execute("SELECT mailbox_id FROM alert_emails WHERE mailbox_id IS NOT NULL")}
        new_ids, seen = [], set()
        for mid in source.list_ids(folder_id, after):
            if mid not in known and mid not in seen:
                new_ids.append(mid)
                seen.add(mid)
        write_state(conn, progress_total=len(new_ids))
        for done, mid in enumerate(new_ids, 1):
            try:
                raw = source.fetch_raw(folder_id, mid)
            except WrongFolder:
                continue
            alerts.process_message(conn, raw, origin="mailbox", mailbox_id=mid, run_id=run_id, rules=rules)
            write_state(conn, progress_done=done)
    except AuthRevoked:
        error, detail = "auth_revoked", "autorización revocada: vuelve a autorizar el buzón"
        write_state(conn, auth_state="revoked", auto_sync="paused_auth")
    except FolderNotFound:
        error = "folder_not_found"
        detail = f"carpeta {state['label_name']} no encontrada"
    except SourceUnavailable:
        error, detail = "source_unavailable", "buzón no disponible: se reintentará en la próxima sincronización"
    except BaseException as exc:  # unexpected, incl. KeyboardInterrupt/SystemExit: finalise, then re-raise
        write_state(conn, last_attempt_status="failed", last_error=type(exc).__name__,
                    last_error_at=_now().isoformat(timespec="seconds"), running_run_id=None)
        alerts.finish_run(conn, run_id, "failed", type(exc).__name__)
        raise

    finished = _now().isoformat(timespec="seconds")
    if error:
        write_state(conn, last_attempt_status="failed", last_error=detail, last_error_at=finished,
                    running_run_id=None)
        alerts.finish_run(conn, run_id, "failed", error)
    else:
        write_state(conn, last_attempt_status="ok", last_success_at=finished, last_error=None,
                    running_run_id=None)
        alerts.finish_run(conn, run_id, "ok", run_error)
    row = conn.execute("SELECT n_found, n_imported, n_already, n_rejected FROM import_runs WHERE run_id=?",
                       (run_id,)).fetchone()
    return _summary("error" if error else "ok", error, run_id=run_id, notice=notice, **dict(row))
