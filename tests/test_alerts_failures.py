"""Unreadable emails are reported, never dropped (T043, US4, FR-009, FR-010, FR-017).

Every bad email is built in memory from an anonymised fixture in tests/fixtures/emails/ by mutation
(remove the card, re-wrap as a forward, add a text/plain part); no email format is invented and no
mutated .eml is written to the repository.
"""
import email
import re
from email import policy
from email.message import EmailMessage

import pytest

from app import alerts, zones

from .conftest import EMAILS

PRICE_DROP = "2026-10-23_bajada-de-precio_viviendas-en-tu-zona-personalizada_112658090.eml"
NEW_BUILD = "2026-10-22_nueva-obra-nueva_obra-nueva-en-tu-zona-personalizada_112882173.eml"
OLD_2021 = "2021-03-10_nuevo-piso_viviendas-tu-zona-personalizada_93231141.eml"
CARD_RE = re.compile(r"<!--\s*inicio inmueble\s*-->.*?<!--\s*link contactar\s*-->", re.S)


@pytest.fixture(autouse=True)
def no_aliases(tmp_path, monkeypatch):
    monkeypatch.setattr(zones, "ALIASES_PATH", tmp_path / "zone_aliases.yaml")


# ---------------------------------------------------------------- helpers

def _load(name: str) -> EmailMessage:
    return email.message_from_bytes((EMAILS / name).read_bytes(), policy=policy.default)


def _set_header(msg, name, value):
    del msg[name]
    msg[name] = value


def _truncated(name: str, message_id: str) -> bytes:
    """The fixture with its listing card removed from the HTML part (layout differs from the sample)."""
    msg = _load(name)
    body = msg.get_body(preferencelist=("html",))
    html = body.get_content()
    assert CARD_RE.search(html), "fixture no longer has a card to remove"
    body.set_content(CARD_RE.sub("", html), subtype="html")
    _set_header(msg, "Message-ID", message_id)
    return msg.as_bytes()


def _not_alert() -> bytes:
    """A plain message from somebody else; only the sender decides it is not a portal alert."""
    msg = EmailMessage()
    msg["From"] = "amigo@example.invalid"
    msg["To"] = "casa@example.invalid"
    msg["Subject"] = "Comida del sábado"
    msg["Date"] = "Fri, 23 Oct 2026 10:00:00 +0200"
    msg["Message-ID"] = "<not-alert-1@example.invalid>"
    msg.set_content("Nos vemos el sábado.")
    return msg.as_bytes()


def _forward_by_subject(name: str) -> bytes:
    msg = _load(name)
    _set_header(msg, "Subject", "Fwd: " + str(msg["Subject"]))
    _set_header(msg, "Message-ID", "<fwd-subject-1@example.invalid>")
    return msg.as_bytes()


def _forward_as_attachment(name: str) -> bytes:
    inner = _load(name)
    outer = EmailMessage()
    outer["From"] = "familiar@example.invalid"
    outer["To"] = "casa@example.invalid"
    outer["Subject"] = "mira esta casa"  # no "Fwd:" prefix: only the message/rfc822 part marks the forward
    outer["Date"] = "Sat, 24 Oct 2026 09:00:00 +0200"
    outer["Message-ID"] = "<fwd-attached-1@example.invalid>"
    outer.set_content("Te la reenvío.")
    outer.add_attachment(inner)  # EmailMessage attachment -> message/rfc822
    assert "message/rfc822" in {p.get_content_type() for p in outer.walk()}
    return outer.as_bytes()


def _with_text_part(name: str) -> bytes:
    msg = _load(name)
    msg.add_attachment("Versión de solo texto del aviso.", subtype="plain")
    assert "text/plain" in {p.get_content_type() for p in msg.walk()}
    _set_header(msg, "Message-ID", "<with-text-1@example.invalid>")
    return msg.as_bytes()


def _process(conn, raw: bytes, file_name: str = "mutated.eml") -> alerts.Outcome:
    run_id = alerts.start_run(conn, "file_cli")
    return alerts.process_message(conn, raw, origin="file", file_name=file_name, run_id=run_id)


def _state(conn):
    """Everything a failed email must leave untouched."""
    return (
        [tuple(r) for r in conn.execute("SELECT * FROM listings ORDER BY id")],
        [tuple(r) for r in conn.execute("SELECT * FROM sightings ORDER BY email_id, listing_id")],
    )


def _stored(conn, email_id):
    return conn.execute("SELECT * FROM alert_emails WHERE email_id=?", (email_id,)).fetchone()


def _assert_kept_and_inert(conn, out, raw, before, outcome, reason_part):
    """Outcome and reason recorded, raw kept byte for byte, nothing created or changed (FR-009, FR-010)."""
    assert out.outcome == outcome
    assert reason_part in out.reason
    assert out.listing_id is None and out.listing_change is None
    row = _stored(conn, out.email_id)
    assert row["outcome"] == outcome and reason_part in row["reason"]
    assert bytes(row["raw"]) == raw
    assert _state(conn) == before
    assert conn.execute("SELECT COUNT(*) FROM sightings WHERE email_id=?", (out.email_id,)).fetchone()[0] == 0


# ---------------------------------------------------------------- tests

def test_failures_reported(conn, no_network):
    """US4-1, US4-2, FR-009: valid fixtures already imported, then a non-alert and a truncated email."""
    good = alerts.import_paths(conn, [EMAILS / PRICE_DROP, EMAILS / NEW_BUILD])
    assert (good["n_imported"], good["n_failed"], good["n_rejected"]) == (2, 0, 0)
    before = _state(conn)
    assert len(before[0]) == 2 and len(before[1]) == 2

    # US4-1: not an alert -> rejected with the stated reason
    raw = _not_alert()
    out = _process(conn, raw)
    _assert_kept_and_inert(conn, out, raw, before, "rejected", "no es un email de alerta reconocido")
    assert out.reason == "no es un email de alerta reconocido"

    # US4-2: same listing as an imported one but the card is gone -> failed, what was expected and found
    raw = _truncated(PRICE_DROP, "<truncated-1@example.invalid>")
    out = _process(conn, raw)
    _assert_kept_and_inert(conn, out, raw, before, "failed", "se esperaba")
    # removing the card also removes the titled listing link, so the reader's first unmet expectation is
    # the title; the test only requires expected + found evidence, not which one the reader reports first
    m = re.search(r"se esperaba (?P<expected>.+), encontrado (?P<found>.+)", out.reason)
    assert m and m["expected"].strip() and m["found"].strip()


def test_failures_listed_in_import_summary(conn, tmp_path, no_network):
    """The run summary names each rejected/failed email with outcome and reason; the valid one imports."""
    (tmp_path / "in").mkdir()
    (tmp_path / "in" / "a-valid.eml").write_bytes((EMAILS / NEW_BUILD).read_bytes())
    (tmp_path / "in" / "b-not-alert.eml").write_bytes(_not_alert())
    (tmp_path / "in" / "c-truncated.eml").write_bytes(_truncated(PRICE_DROP, "<truncated-2@example.invalid>"))

    summary = alerts.import_paths(conn, [tmp_path / "in"])

    assert (summary["n_found"], summary["n_imported"], summary["n_rejected"], summary["n_failed"]) == (3, 1, 1, 1)
    by_outcome = {p["outcome"]: p for p in summary["problems"]}
    assert set(by_outcome) == {"rejected", "failed"}
    assert by_outcome["rejected"]["reason"] == "no es un email de alerta reconocido"
    assert "se esperaba" in by_outcome["failed"]["reason"]
    assert by_outcome["failed"]["subject"]
    assert conn.execute("SELECT COUNT(*) FROM listings").fetchone()[0] == 1


def test_2021_fixture_rejected_as_unsupported(conn, no_network):
    raw = (EMAILS / OLD_2021).read_bytes()
    before = _state(conn)
    out = _process(conn, raw, OLD_2021)
    _assert_kept_and_inert(conn, out, raw, before, "rejected", "tipo de alerta no soportado")
    assert out.reason == "tipo de alerta no soportado"


@pytest.mark.parametrize("build, reason", [
    pytest.param(_forward_by_subject, "reenvío sin muestra", id="forward-subject"),
    pytest.param(_forward_as_attachment, "reenvío sin muestra", id="forward-rfc822-attachment"),
    pytest.param(_with_text_part, "formato sin muestra", id="added-text-plain-part"),
])
def test_forward_and_text_layouts_fail_without_listing(conn, no_network, build, reason):
    """FR-017: layouts without a real sample are failed, kept, and never create or change a listing."""
    alerts.import_paths(conn, [EMAILS / PRICE_DROP])  # a listing from the same fixture already exists
    before = _state(conn)
    raw = build(PRICE_DROP)

    out = _process(conn, raw)

    _assert_kept_and_inert(conn, out, raw, before, "failed", reason)
    assert out.reason == reason
    assert _stored(conn, out.email_id)["forwarded"] == (0 if build is _with_text_part else 1)


def test_forward_and_text_layouts_on_empty_database(conn, no_network):
    """Same with no earlier listing: nothing at all is created."""
    for build in (_forward_by_subject, _forward_as_attachment, _with_text_part):
        out = _process(conn, build(NEW_BUILD))
        assert out.outcome == "failed"
    assert conn.execute("SELECT COUNT(*) FROM listings").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM sightings").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM alert_emails WHERE outcome='failed'").fetchone()[0] == 3


def test_reprocess_with_newer_reader_imports_failed_email(conn, no_network, monkeypatch):
    """US4-3: a failed email is re-read from its stored raw by a newer reader that understands it.

    There is no simple real layout change to monkeypatch, so the 'newer reader' is a patched read() that
    returns the result of the current reader on the intact fixture, plus a newer READER_VERSION.
    Calls alerts.reprocess (T044), which does not exist yet."""
    raw = _truncated(PRICE_DROP, "<truncated-3@example.invalid>")
    out = _process(conn, raw)
    assert out.outcome == "failed"
    email_id = out.email_id
    original = _stored(conn, email_id)
    old_version = original["reader_version"]
    assert conn.execute("SELECT COUNT(*) FROM listings").fetchone()[0] == 0

    intact = alerts.reader.read(_load(PRICE_DROP))
    assert intact.listings and not intact.problems
    newer = old_version + "-newer"
    monkeypatch.setattr(alerts.reader, "READER_VERSION", newer)
    monkeypatch.setattr(alerts.reader, "read", lambda msg: intact)

    summary = alerts.reprocess(conn, scope="failed")

    row = _stored(conn, email_id)
    assert row["outcome"] == "imported" and row["reason"] is None
    assert row["reader_version"] == newer
    assert bytes(row["raw"]) == raw == bytes(original["raw"])  # the original raw is never rewritten
    assert row["content_hash"] == original["content_hash"]
    code = intact.listings[0].listing_code
    assert conn.execute("SELECT COUNT(*) FROM listings WHERE id=?", (f"idealista:{code}",)).fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM sightings WHERE email_id=?", (email_id,)).fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM alert_emails").fetchone()[0] == 1  # no duplicate row
    assert summary["n_imported"] == 1 and summary["n_failed"] == 0
    assert conn.execute("SELECT kind FROM import_runs WHERE run_id=?", (summary["run_id"],)).fetchone()[0] == "reprocess"


def test_reprocess_with_same_reader_leaves_failed_email_as_is(conn, no_network):
    """T044 re-reads emails whose reader_version is older than the current one: with an unchanged
    reader a failed email stays failed and still creates nothing."""
    out = _process(conn, _truncated(PRICE_DROP, "<truncated-4@example.invalid>"))
    reason = out.reason

    summary = alerts.reprocess(conn, scope="failed")

    row = _stored(conn, out.email_id)
    assert row["outcome"] == "failed" and row["reason"] == reason
    assert summary["n_imported"] == 0
    assert conn.execute("SELECT COUNT(*) FROM listings").fetchone()[0] == 0
