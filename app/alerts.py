"""Alert email pipeline shared by mailbox sync and file import: store every message as received, read it,
record its sighting and re-derive the listing, one transaction per message (FR-009, FR-010)."""
from __future__ import annotations

import email
import hashlib
import json
import mailbox
import re
from dataclasses import dataclass, field
from datetime import datetime
from email import policy
from email.utils import parseaddr
from pathlib import Path

from . import derive
from .db import dumps
from .providers import idealista_alert as reader

FORWARD_RE = re.compile(r"^\s*(fwd?|rv|reenviado)\s*:", re.I)
PORTAL_SENDERS = {reader.SENDER, *reader.OLD_SENDERS}

REASON_NOT_ALERT = "no es un email de alerta reconocido"
REASON_UNSUPPORTED = "tipo de alerta no soportado"
REASON_FORWARD = "reenvío sin muestra"
REASON_TEXT_PART = "formato sin muestra"
REASON_UNSUPPORTED_FILE = "unsupported file format: save as .eml"
REASON_UNREADABLE_FILE = "unreadable file: expected an .eml or .mbox file"
EMAIL_SUFFIXES = (".eml", ".mbox")
REASON_NO_DATE = "fecha del email: se esperaba una cabecera Date válida"

SIGHTING_FIELDS = ("price", "previous_price", "area_m2", "bedrooms", "floor", "exterior", "elevator", "garage",
                   "type_text", "property_type", "new_build_stated", "development", "unit_description",
                   "location_text", "link_tracking", "link_direct", "raw_block")


@dataclass
class Outcome:
    email_id: str
    outcome: str                      # imported | already | rejected | failed
    reason: str | None = None
    listing_id: str | None = None
    listing_change: str | None = None  # new | updated | None
    notices: list[str] = field(default_factory=list)


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def start_run(conn, kind: str) -> int:
    cur = conn.execute("INSERT INTO import_runs(kind, started_at, status) VALUES(?,?,'running')", (kind, _now()))
    conn.commit()
    return cur.lastrowid


def finish_run(conn, run_id: int, status: str, error: str | None = None) -> None:
    conn.execute("UPDATE import_runs SET status=?, error=?, finished_at=? WHERE run_id=?",
                 (status, error, _now(), run_id))
    conn.commit()


def _count(conn, run_id, out: Outcome, price_changed: bool) -> None:
    run = conn.execute("SELECT notes FROM import_runs WHERE run_id=?", (run_id,)).fetchone()
    notes = json.loads(run["notes"] or "[]") + [{"email_id": out.email_id, "text": n} for n in out.notices]
    conn.execute(
        f"UPDATE import_runs SET n_found=n_found+1, n_{out.outcome}=n_{out.outcome}+1, "
        "n_new_listings=n_new_listings+?, n_updated_listings=n_updated_listings+?, "
        "n_price_changes=n_price_changes+?, notes=? WHERE run_id=?",
        (int(out.listing_change == "new"), int(out.listing_change == "updated"), int(price_changed),
         dumps(notes), run_id))


def _alert_date(msg) -> str | None:
    try:
        dt = msg["Date"].datetime
    except (AttributeError, TypeError, ValueError):
        return None
    return dt.isoformat() if dt else None


def _problem_reason(problems) -> str:
    return "; ".join(f"{p.where}: se esperaba {p.expected}, encontrado {p.found}" for p in problems)


def process_message(conn, raw: bytes, *, origin: str, file_name: str | None = None,
                    mailbox_id: str | None = None, run_id: int) -> Outcome:
    msg = email.message_from_bytes(raw, policy=policy.default)
    content_hash = hashlib.sha256(raw).hexdigest()
    email_id = str(msg.get("Message-ID") or "").strip() or f"sha256:{content_hash}"

    with conn:
        if conn.execute("SELECT 1 FROM alert_emails WHERE email_id=? OR (mailbox_id IS NOT NULL AND mailbox_id=?)",
                        (email_id, mailbox_id)).fetchone():
            conn.execute("UPDATE alert_emails SET last_run_id=? WHERE email_id=? OR mailbox_id=?",
                         (run_id, email_id, mailbox_id))
            out = Outcome(email_id, "already")
            _count(conn, run_id, out, False)
            return out

        sender = parseaddr(str(msg.get("From", "")))[1].lower()
        subject = str(msg.get("Subject", ""))
        alert_date = _alert_date(msg)
        types = {part.get_content_type() for part in msg.walk()}
        forwarded = bool(FORWARD_RE.match(subject)) or "message/rfc822" in types
        row = {"email_id": email_id, "mailbox_id": mailbox_id, "content_hash": content_hash, "origin": origin,
               "file_name": file_name, "sender": sender, "subject": subject, "alert_date": alert_date,
               "forwarded": int(forwarded), "reader_version": reader.READER_VERSION, "raw": raw,
               "first_run_id": run_id, "last_run_id": run_id}
        result = None
        if forwarded:
            out = Outcome(email_id, "failed", REASON_FORWARD)
        elif "text/plain" in types and sender in PORTAL_SENDERS:
            out = Outcome(email_id, "failed", REASON_TEXT_PART)
        else:
            result = reader.read(msg)
            row.update(alert_type=result.alert_type, search_name=result.search_name)
            if result.alert_type == "not_alert":
                out = Outcome(email_id, "rejected", REASON_NOT_ALERT)
            elif result.alert_type == "unsupported":
                out = Outcome(email_id, "rejected", REASON_UNSUPPORTED)
            elif result.problems or len(result.listings) != 1:
                out = Outcome(email_id, "failed", _problem_reason(result.problems) or
                              f"anuncios en el email: se esperaba 1, encontrado {len(result.listings)}")
            elif alert_date is None:
                out = Outcome(email_id, "failed", REASON_NO_DATE)
            else:
                out = Outcome(email_id, "imported", notices=list(result.notices))
        row.update(outcome=out.outcome, reason=out.reason)
        conn.execute(f"INSERT INTO alert_emails({','.join(row)}) VALUES({','.join('?' * len(row))})",
                     list(row.values()))

        price_changed = False
        if out.outcome == "imported":
            block = result.listings[0]
            out.listing_id = f"idealista:{block.listing_code}"
            before = conn.execute("SELECT * FROM listings WHERE id=?", (out.listing_id,)).fetchone()
            sighting = {"email_id": email_id, "listing_id": out.listing_id, "alert_type": result.alert_type,
                        "seen_at": alert_date, "unrecognised": dumps(result.notices),
                        **{f: getattr(block, f) for f in SIGHTING_FIELDS}}
            conn.execute(f"INSERT INTO sightings({','.join(sighting)}) VALUES({','.join('?' * len(sighting))})",
                         list(sighting.values()))
            derive.derive_listing(conn, out.listing_id)
            after = conn.execute("SELECT * FROM listings WHERE id=?", (out.listing_id,)).fetchone()
            if before is None:
                out.listing_change = "new"
            elif tuple(before) != tuple(after):
                out.listing_change = "updated"
                price_changed = before["price"] != after["price"]
        _count(conn, run_id, out, price_changed)
    return out


def _expand(paths) -> list[Path]:
    """Folders (non-recursive) become their .eml/.mbox files; other paths are kept as given."""
    files: list[Path] = []
    for path in map(Path, paths):
        if path.is_dir():
            files += sorted(p for p in path.iterdir() if p.is_file() and p.suffix.lower() in EMAIL_SUFFIXES)
        else:
            files.append(path)
    return files


def _read_file(path: Path) -> list[tuple[str, bytes]]:
    """Return (file_name, raw) for each message in an .eml or .mbox file; raise ValueError if unsupported."""
    suffix = path.suffix.lower()
    if suffix == ".eml":
        return [(path.name, path.read_bytes())]
    if suffix == ".mbox":
        box = mailbox.mbox(str(path), create=False)
        try:
            return [(f"{path.name}#{i}", box.get_bytes(key)) for i, key in enumerate(box.keys())]
        finally:
            box.close()
    raise ValueError(REASON_UNSUPPORTED_FILE)


def _sort_key(item: tuple[str, bytes]) -> float:
    """Oldest Date first; messages without a valid Date go last."""
    try:
        msg = email.message_from_bytes(item[1], policy=policy.default)
        return msg["Date"].datetime.timestamp()
    except (AttributeError, TypeError, ValueError, OverflowError, OSError):
        return float("inf")


def _count_file_failure(conn, run_id: int) -> None:
    conn.execute("UPDATE import_runs SET n_found=n_found+1, n_failed=n_failed+1 WHERE run_id=?", (run_id,))
    conn.commit()


def import_paths(conn, paths, kind: str = "file_cli") -> dict:
    """Import .eml/.mbox files and folders; return the run summary with its problems and notices.

    A file that cannot be read or is not .eml/.mbox counts as one found and one failed item."""
    run_id = start_run(conn, kind)
    problems: list[dict] = []
    notices: list[dict] = []
    try:
        items: list[tuple[str, bytes]] = []
        for path in _expand(paths):
            try:
                items += _read_file(path)
            except (ValueError, OSError, mailbox.Error) as exc:
                reason = REASON_UNSUPPORTED_FILE if isinstance(exc, ValueError) else REASON_UNREADABLE_FILE
                _count_file_failure(conn, run_id)
                problems.append({"email_id": path.name, "alert_date": None, "subject": None,
                                 "outcome": "failed", "reason": reason})
        for file_name, raw in sorted(items, key=_sort_key):
            out = process_message(conn, raw, origin="file", file_name=file_name, run_id=run_id)
            if out.outcome == "already":
                continue
            row = conn.execute("SELECT subject, alert_date FROM alert_emails WHERE email_id=?",
                               (out.email_id,)).fetchone()
            ref = {"email_id": out.email_id, "alert_date": row["alert_date"], "subject": row["subject"]}
            if out.outcome in ("rejected", "failed"):
                problems.append({**ref, "outcome": out.outcome, "reason": out.reason})
            notices += [{**ref, "text": text} for text in out.notices]
    except Exception as exc:
        finish_run(conn, run_id, "failed", type(exc).__name__)
        raise
    finish_run(conn, run_id, "ok")
    summary = dict(conn.execute("SELECT * FROM import_runs WHERE run_id=?", (run_id,)).fetchone())
    summary.pop("notes", None)
    return {**summary, "problems": problems, "notices": notices}
