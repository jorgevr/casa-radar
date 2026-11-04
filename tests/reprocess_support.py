"""Shared helpers for the re-process tests (T044, T045). Not a test module.

Every email here is a real anonymised fixture from tests/fixtures/emails/, mutated in memory only (no new
email format is invented, Article VI): a removed card marker, an added text/plain part, or a shifted
follow-up of the same listing. Mutations were checked against the reader by hand:
  * "inicio inmueble" -> "inicio xinmueble"      reader: problem "tarjeta del anuncio", found "0 tarjetas"
  * 645.000->630.000 and 670.000->645.000 plus a later Date: reads as a drop 645.000 -> 630.000.
"""
import email
import re
from email import policy
from email.mime.text import MIMEText

from app import alerts
from app.providers import idealista_alert as reader

from .conftest import EMAILS

NEW_VERSION = "idealista-2026.11"  # sorts after the current "idealista-2026.10"

DROP_NAME = "2026-10-26_bajada-de-precio_chalets-en-tu-zona-personalizada_112842548.eml"  # 670.000 -> 645.000
OTHER_DROP_NAME = "2026-10-23_bajada-de-precio_viviendas-en-tu-zona-personalizada_112658090.eml"  # 680.000 -> 650.000
NEW_NAME = "2026-10-27_nuevo-chalet-pareado_chalets-en-tu-zona-personalizada_112923327.eml"  # 560.000
OLD_2021_NAME = "2021-03-10_nuevo-piso_viviendas-tu-zona-personalizada_93231141.eml"
DROP_LISTING = "idealista:112842548"
OTHER_DROP_LISTING = "idealista:112658090"


def fixture(name: str) -> bytes:
    return (EMAILS / name).read_bytes()


def message_id(raw: bytes) -> str:
    return str(email.message_from_bytes(raw, policy=policy.default)["Message-ID"])


def _header(raw: bytes, name: str, value: str) -> bytes:
    return re.sub(rb"(?im)^" + name.encode() + rb":[^\r\n]*", f"{name}: {value}".encode(), raw, count=1)


def reid(raw: bytes, tag: str) -> bytes:
    return _header(raw, "Message-ID", f"<{tag}@example.invalid>")


def truncated(raw: bytes, tag: str) -> bytes:
    """The listing card's start marker removed: the reader reports a failed email, 0 cards found."""
    assert raw.count(b"inicio inmueble") == 1
    return reid(raw.replace(b"inicio inmueble", b"inicio xinmueble"), tag)


def with_text_part(raw: bytes, tag: str) -> bytes:
    """A text/plain part added: failed "formato sin muestra" before the reader is even asked."""
    msg = email.message_from_bytes(raw, policy=policy.default)
    msg.attach(MIMEText("texto", "plain"))
    return reid(msg.as_bytes(), tag)


def followup_drop(raw: bytes, tag: str) -> bytes:
    """DROP_NAME two days later, one more drop: 645.000 -> 630.000 on 2026-10-28."""
    out = raw.replace(b"645.000", b"630.000").replace(b"670.000", b"645.000")
    return reid(_header(out, "Date", "Wed, 28 Oct 2026 12:28:28 +0100"), tag)


def store(conn, raws, kind="file_cli"):
    """Store emails one by one in the given order through the public pipeline (no files needed)."""
    run_id = alerts.start_run(conn, kind)
    outs = [alerts.process_message(conn, raw, origin="file", file_name=f"m{i}.eml", run_id=run_id)
            for i, raw in enumerate(raws)]
    alerts.finish_run(conn, run_id, "ok")
    return outs


def newer_reader(monkeypatch, understands=None, problem=None):
    """Pretend a newer reader is installed: READER_VERSION moves on, and
    - emails whose Message-ID is a key of `understands` are read as the (full) email stored under that key's value;
    - if `problem` is given, every email that would otherwise be read comes back with that single Problem."""
    understands = understands or {}
    original = reader.read
    monkeypatch.setattr(reader, "READER_VERSION", NEW_VERSION)

    def read(msg):
        mid = str(msg["Message-ID"])
        if mid in understands:
            return original(email.message_from_bytes(understands[mid], policy=policy.default))
        result = original(msg)
        if problem is not None and result.alert_type in ("new_listing", "price_drop"):
            return reader.ReadResult(result.alert_type, result.search_name, problems=[problem])
        return result

    monkeypatch.setattr(reader, "read", read)


def table(conn, sql, *args):
    return [dict(r) for r in conn.execute(sql, args).fetchall()]


def snapshot(conn):
    """Everything a re-process may touch, without run bookkeeping (first_run_id, last_run_id)."""
    return {
        "listings": table(conn, "SELECT * FROM listings ORDER BY id"),
        "sightings": table(conn, "SELECT * FROM sightings ORDER BY email_id, listing_id"),
        "history": table(conn, "SELECT listing_id, day, price, origin FROM price_history "
                               "ORDER BY listing_id, day, origin, price"),
        "emails": table(conn, "SELECT email_id, content_hash, outcome, reason, reader_version, alert_type, "
                              "search_name, category, raw FROM alert_emails ORDER BY email_id"),
    }


def without_run_columns(snap):
    out = dict(snap)
    out["listings"] = [{k: v for k, v in row.items() if k != "first_run_id"} for row in snap["listings"]]
    return out
