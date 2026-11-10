"""FU6a: reprocess rules decided by the user (review T044 F3, FU5 F1) and failed-email excerpts (T043).

  1. Old sightings are KEPT when a re-read does not produce 'imported' (failed or rejected). The listing stays
     derived from them; raw/content_hash unchanged; the alert_emails row records the new outcome, reason and
     reader_version. When the new read is 'imported' the email's sightings are replaced (as before), also when
     the new read points at another listing code (the old listing row is not deleted).
  2. An unexpected exception while re-reading one email is visible afterwards: GET /api/runs/{id} lists a
     problem for that email whose reason is the exception class name only, the email's stored outcome and
     sightings are unchanged, and the entry survives a new connection (it is persisted, not only returned by
     POST /api/alerts/reprocess). No schema change is needed: import_runs.notes already carries per-run
     entries (file failures are listed the same way), so the entry can be stored there.
  3. A failed email's reason (the 'se esperaba ..., encontrado ...' ones) also carries a short excerpt of the
     email's own visible text: whitespace collapsed, URLs removed, at most 120 characters, a prefix of the
     cleaned visible text, never the whole body, deterministic. Fixed-phrase reasons stay exactly as they are.

Every email is an anonymised fixture mutated in memory (no new email format is invented). Expected values:
  * DROP (112842548) 2026-10-26 at 645.000, followup_drop 2026-10-28 at 630.000 (hand calculation in
    reprocess_support); the listing's price is the latest sighting's: 630.000, last_seen 2026-10-28.
  * OTHER_DROP is listing 112658090 at 650.000.
  * The injected visible text "Mira<newline><tab> https://example.invalid/x?a=1 <newline> y   http://otro.invalid/p fin"
    cleans, by hand, to "Mira y fin": the two links go, the whitespace collapses.
"""
import base64
import difflib
import email
import re
import sqlite3
import time
from email import policy
from email.message import EmailMessage
from html.parser import HTMLParser

import pytest
from fastapi.testclient import TestClient

from app import alerts, zones
from app.main import create_app
from app.providers import idealista_alert as reader

from .conftest import EMAILS, EXAMPLE_NEEDS
from .reprocess_support import (DROP_LISTING, DROP_NAME, NEW_VERSION, OTHER_DROP_LISTING, OTHER_DROP_NAME, fixture,
                                followup_drop, message_id, newer_reader, reid, store, table, truncated,
                                with_text_part)

CARD_RE = re.compile(r"<!--\s*inicio inmueble\s*-->.*?<!--\s*link contactar\s*-->", re.S)
URL_RE = re.compile(r"https?://\S+")
INJECTED = "Mira\n\t https://example.invalid/x?a=1 \n y   http://otro.invalid/p fin"


@pytest.fixture(autouse=True)
def no_aliases(tmp_path, monkeypatch):
    monkeypatch.setattr(zones, "ALIASES_PATH", tmp_path / "zone_aliases.yaml")


def _email(conn, email_id):
    return dict(conn.execute("SELECT * FROM alert_emails WHERE email_id=?", (email_id,)).fetchone())


def _listing(conn, listing_id):
    return dict(conn.execute("SELECT * FROM listings WHERE id=?", (listing_id,)).fetchone())


def _sightings(conn, email_id):
    return table(conn, "SELECT * FROM sightings WHERE email_id=? ORDER BY listing_id", email_id)


def _not_alert_version_of(raw: bytes, tag: str) -> bytes:
    """Same email from a different sender: the reader answers 'not an alert' (rejected)."""
    out = re.sub(rb"(?im)^From:[^\r\n]*", b"From: amigo@example.invalid", raw, count=1)
    return reid(out, tag)


# -- 1. F3: old sightings are kept unless the new read is imported -----------------------------------------
@pytest.mark.parametrize("kind", ["failed", "rejected"])
def test_reread_that_is_not_imported_keeps_the_sightings_and_the_derived_listing(conn, monkeypatch, no_network, kind):
    first, follow = fixture(DROP_NAME), followup_drop(fixture(DROP_NAME), "followup-1")
    store(conn, [first, follow])
    follow_id = message_id(follow)
    assert _listing(conn, DROP_LISTING)["price"] == 630000  # precondition (hand calculation, module docstring)
    sightings_before = _sightings(conn, follow_id)
    assert len(sightings_before) == 1
    listing_before = _listing(conn, DROP_LISTING)
    row_before = _email(conn, follow_id)
    unreadable = (truncated(follow, "x-trunc") if kind == "failed" else _not_alert_version_of(follow, "x-other"))
    newer_reader(monkeypatch, understands={follow_id: unreadable})

    summary = alerts.reprocess(conn, scope="all")

    assert summary["n_found"] == 2 and summary["n_imported"] == 1
    assert summary[f"n_{kind}"] == 1
    # the sightings are kept as they were, and the listing is still what they derive to
    assert _sightings(conn, follow_id) == sightings_before
    assert table(conn, "SELECT COUNT(*) AS n FROM sightings") == [{"n": 2}]
    assert _listing(conn, DROP_LISTING) == listing_before
    assert _listing(conn, DROP_LISTING)["price"] == 630000
    # the email row records the new attempt; raw and hash are untouched
    row = _email(conn, follow_id)
    assert row["outcome"] == kind
    assert row["reader_version"] == NEW_VERSION
    assert row["reason"] != row_before["reason"] and row["reason"]
    assert row["last_run_id"] == summary["run_id"]
    assert row["raw"] == row_before["raw"] and row["content_hash"] == row_before["content_hash"]
    assert [(p["email_id"], p["outcome"]) for p in summary["problems"]] == [(follow_id, kind)]


def test_reread_that_is_imported_still_replaces_the_sightings(conn, monkeypatch, no_network):
    """Pin: the keep-rule applies only to non-imported re-reads."""
    (out,) = store(conn, [fixture(DROP_NAME)])
    patched = fixture(DROP_NAME).replace(b"645.000", b"640.000").replace(b"670.000", b"660.000")
    assert patched != fixture(DROP_NAME)
    newer_reader(monkeypatch, understands={out.email_id: patched})

    summary = alerts.reprocess(conn, scope="all")

    assert summary["n_imported"] == 1
    sightings = _sightings(conn, out.email_id)
    assert [(s["listing_id"], s["price"], s["previous_price"]) for s in sightings] == [(DROP_LISTING, 640000, 660000)]
    assert _listing(conn, DROP_LISTING)["price"] == 640000


def test_reread_imported_for_another_listing_code_replaces_the_sightings(conn, monkeypatch, no_network):
    """Documented as-is behaviour: the old sighting goes, the new listing is created, and the old listing row
    is not deleted (it keeps its values, with no sighting left as source)."""
    (out,) = store(conn, [fixture(DROP_NAME)])
    old_listing = _listing(conn, DROP_LISTING)
    newer_reader(monkeypatch, understands={out.email_id: fixture(OTHER_DROP_NAME)})

    summary = alerts.reprocess(conn, scope="all")

    assert summary["n_imported"] == 1
    assert [s["listing_id"] for s in _sightings(conn, out.email_id)] == [OTHER_DROP_LISTING]
    assert _listing(conn, OTHER_DROP_LISTING)["price"] == 650000
    assert _listing(conn, DROP_LISTING) == old_listing  # not deleted, not blanked
    assert _email(conn, out.email_id)["outcome"] == "imported"


# -- 2. an unexpected exception is visible in GET /api/runs/{id} -------------------------------------------
def _import(client, raws):
    files = [{"name": f"m{i}.eml", "content_base64": base64.b64encode(r).decode("ascii")}
             for i, r in enumerate(raws)]
    resp = client.post("/api/alerts/import", json={"files": files})
    assert resp.status_code == 200, resp.text


def test_unexpected_exception_is_listed_in_the_run_detail_and_persisted(tmp_path, monkeypatch):
    # no `no_network` here: its guard also blocks the event loop's local socketpair that TestClient needs;
    # nothing in this test (in-process app, fixtures, a patched reader) can reach the network.
    needs = tmp_path / "needs.yaml"
    needs.write_text(EXAMPLE_NEEDS.read_text(encoding="utf-8"), encoding="utf-8")
    db_path = str(tmp_path / "t.db")
    raws = [fixture(OTHER_DROP_NAME), fixture(DROP_NAME)]
    boom = message_id(raws[1])
    original = reader.read

    def flaky(msg):
        if str(msg["Message-ID"]) == boom:
            raise RuntimeError("secret-detail C:\\Users\\someone\\private.txt")
        return original(msg)

    with TestClient(create_app(db_path, str(needs))) as client:
        _import(client, raws)
        monkeypatch.setattr(reader, "read", flaky)
        resp = client.post("/api/alerts/reprocess", json={"scope": "all"})
        assert resp.status_code == 200, resp.text
        run_id = resp.json()["run_id"]
        detail = client.get(f"/api/runs/{run_id}").json()

    def check(detail):
        entries = [p for p in detail["problems"] if p["email_id"] == boom]
        assert len(entries) == 1  # listed once
        assert entries[0]["outcome"] == "failed"
        assert entries[0]["reason"] == "RuntimeError"  # the class only: no message, no path
        assert "secret" not in repr(detail) and "private.txt" not in repr(detail)
        assert detail["n_failed"] == 1 and detail["n_found"] == 2

    check(detail)
    monkeypatch.setattr(reader, "read", original)

    # persisted: a new app on the same database file (new connection) still lists it
    with TestClient(create_app(db_path, str(needs))) as client:
        check(client.get(f"/api/runs/{run_id}").json())

    # the failing email itself is unchanged: outcome imported, its sighting still there
    raw_conn = sqlite3.connect(db_path)
    raw_conn.row_factory = sqlite3.Row
    try:
        row = raw_conn.execute("SELECT outcome, reason, last_run_id FROM alert_emails WHERE email_id=?",
                               (boom,)).fetchone()
        assert row["outcome"] == "imported" and row["last_run_id"] != run_id
        n = raw_conn.execute("SELECT COUNT(*) FROM sightings WHERE email_id=?", (boom,)).fetchone()[0]
        assert n == 1
    finally:
        raw_conn.close()


# -- 3. excerpt of the visible text in failed reasons ----------------------------------------------------
class _Visible(HTMLParser):
    SKIP = ("script", "style", "head", "title")

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.text, self.skip = [], 0

    def handle_starttag(self, tag, attrs):
        self.skip += tag in self.SKIP

    def handle_endtag(self, tag):
        self.skip -= tag in self.SKIP and self.skip > 0

    def handle_data(self, data):
        if not self.skip:
            self.text.append(data)


def _cleaned_visible_text(raw: bytes) -> str:
    """The test's own reading of the visible text: no tags/comments/head, URLs removed, whitespace collapsed."""
    msg = email.message_from_bytes(raw, policy=policy.default)
    html = msg.get_body(preferencelist=("html",)).get_content()
    parser = _Visible()
    parser.feed(html)
    return " ".join(URL_RE.sub(" ", " ".join(parser.text)).split())


def _card_removed_with_injected_text(name: str, tag: str) -> bytes:
    msg = email.message_from_bytes((EMAILS / name).read_bytes(), policy=policy.default)
    body = msg.get_body(preferencelist=("html",))
    html = CARD_RE.sub("", body.get_content())
    html, n = re.subn(r"(<body[^>]*>)", lambda m: m[1] + f"<p>{INJECTED}</p>", html, count=1)
    assert n == 1
    body.set_content(html, subtype="html")
    del msg["Message-ID"]
    msg["Message-ID"] = f"<{tag}@example.invalid>"
    return msg.as_bytes()


def _longest_shared(reason: str, text: str) -> int:
    return difflib.SequenceMatcher(None, reason, text, autojunk=False).find_longest_match(
        0, len(reason), 0, len(text)).size


def test_failed_reason_carries_a_short_clean_excerpt_of_the_visible_text(conn, no_network):
    raw = _card_removed_with_injected_text(DROP_NAME, "excerpt-1")
    visible = _cleaned_visible_text(raw)
    assert visible.startswith("Mira y fin") and len(visible) > 400  # precondition (hand calculation)
    (out,) = store(conn, [raw])
    assert out.outcome == "failed"
    reason = _email(conn, out.email_id)["reason"]
    assert reason == out.reason

    assert re.search(r"se esperaba .+, encontrado .+", reason)  # the existing evidence is intact
    assert "Mira y fin" in reason  # the excerpt, links removed and whitespace collapsed
    assert "http" not in reason and "example.invalid" not in reason and "otro.invalid" not in reason
    assert not re.search(r"[\n\r\t]|\s{2,}", reason)
    # a prefix of the visible text, longer than a token, at most 120 characters, never the whole body
    shared = _longest_shared(reason, visible)
    assert 40 <= shared <= 120, shared
    assert visible[:121] not in reason and visible not in reason


def test_excerpt_is_deterministic_and_also_appears_when_reprocessing(conn, monkeypatch, no_network):
    one = _card_removed_with_injected_text(DROP_NAME, "excerpt-a")
    two = _card_removed_with_injected_text(DROP_NAME, "excerpt-b")  # same body, only the Message-ID differs
    out_a, out_b = store(conn, [one, two])
    assert out_a.outcome == out_b.outcome == "failed"
    assert out_a.reason == out_b.reason

    newer_reader(monkeypatch)  # the same reader logic under a newer version: still fails
    summary = alerts.reprocess(conn, scope="failed")

    assert summary["n_failed"] == 2
    assert {p["reason"] for p in summary["problems"]} == {out_a.reason}
    assert _email(conn, out_a.email_id)["reason"] == out_a.reason


def test_failed_reason_of_the_plain_truncated_fixture_keeps_evidence_and_adds_text(conn, no_network):
    """The truncated fixture (marker removed): evidence plus excerpt, within bounds, no links."""
    raw = truncated(fixture(DROP_NAME), "plain-trunc-1")
    visible = _cleaned_visible_text(raw)
    (out,) = store(conn, [raw])
    assert out.outcome == "failed" and "0 tarjetas" in out.reason
    assert re.search(r"se esperaba .+, encontrado .+", out.reason)
    shared = _longest_shared(out.reason, visible)
    assert 40 <= shared <= 120, shared
    assert "http" not in out.reason


# -- 3b. excerpt hardening (review FU6a F1, F2) ---------------------------------------------------------
LEAD = "palabra " * 40  # 320 visible characters before the hostile markup: the excerpt has something to cut
HOSTILE = {  # about 200 KB each; every shape is malformed markup an HTML parser may take quadratic time on
    "unterminated-a": "<a " * 70_000,
    "unclosed-comments": "<!--" * 50_000,
    "unclosed-charrefs": "&#" * 100_000,
}


def _card_removed_with_html(name: str, tag: str, injected: str, trailer: str = "") -> bytes:
    """Card removed, `injected` right after <body ...>, `trailer` after the last tag (no later '>' can close it)."""
    msg = email.message_from_bytes((EMAILS / name).read_bytes(), policy=policy.default)
    body = msg.get_body(preferencelist=("html",))
    html = CARD_RE.sub("", body.get_content())
    html, n = re.subn(r"(<body[^>]*>)", lambda m: m[1] + injected, html, count=1)
    assert n == 1
    body.set_content(html + trailer, subtype="html")
    del msg["Message-ID"]
    msg["Message-ID"] = f"<{tag}@example.invalid>"
    return msg.as_bytes()


@pytest.mark.parametrize("shape", sorted(HOSTILE))
def test_hostile_markup_is_classified_quickly_with_a_bounded_excerpt(conn, no_network, shape):
    raw = _card_removed_with_html(DROP_NAME, f"hostile-{shape}", f"<p>{LEAD}</p>", HOSTILE[shape])
    assert len(raw) > 150_000  # precondition: a big body

    started = time.perf_counter()
    (out,) = store(conn, [raw])
    elapsed = time.perf_counter() - started

    assert elapsed < 2.0, f"{shape}: classification took {elapsed:.1f}s"  # generous; quadratic parsing takes far longer
    assert out.outcome == "failed"
    reason = _email(conn, out.email_id)["reason"]
    assert reason == out.reason
    assert re.search(r"se esperaba .+, encontrado .+", reason)
    assert "encontrado ninguno" in reason  # precondition: no listing link in this body
    tail = reason.split("encontrado ninguno", 1)[1]  # whatever follows the evidence: separator, label, excerpt
    assert len(tail) <= 120 + 40, len(tail)  # excerpt at most 120 characters plus a short label/separator
    assert "palabra palabra" in tail  # still an excerpt of the visible text (prefix), not dropped
    assert not re.search(r"[\x00-\x1f\x7f]", reason)
    stored = _email(conn, out.email_id)
    assert stored["outcome"] == "failed" and bytes(stored["raw"]) == raw


def test_excerpt_drops_control_characters_bare_www_links_and_email_addresses(conn, no_network):
    # hand calculation: after cleaning, the visible text starts "Contacto ... fin" with ESC and BEL removed,
    # the bare link and the address gone
    injected = "<p>Contacto\x1b[31m ana@example.invalid www.example.invalid/x?a=1 y\x07 fin</p>"
    raw = _card_removed_with_html(DROP_NAME, "controls-1", injected)
    (out,) = store(conn, [raw])
    assert out.outcome == "failed"
    reason = _email(conn, out.email_id)["reason"]
    assert re.search(r"se esperaba .+, encontrado .+", reason)
    assert "Contacto" in reason and "fin" in reason  # the excerpt is there
    assert not re.search(r"[\x00-\x1f\x7f]", reason)  # no ESC, BEL or any other C0 control
    assert "@" not in reason and "ana" not in reason
    assert "www." not in reason and "example.invalid" not in reason
    assert bytes(_email(conn, out.email_id)["raw"]) == raw


# fixed-phrase reasons must not change (pins: they pass now and must keep passing)
def test_non_alert_reason_stays_exactly_the_fixed_phrase(conn, no_network):
    msg = EmailMessage()
    msg["From"] = "amigo@example.invalid"
    msg["Subject"] = "Comida del sábado"
    msg["Date"] = "Fri, 23 Oct 2026 10:00:00 +0200"
    msg["Message-ID"] = "<not-alert-excerpt@example.invalid>"
    msg.set_content("Nos vemos el sábado en https://example.invalid/mesa")
    (out,) = store(conn, [msg.as_bytes()])
    assert (out.outcome, out.reason) == ("rejected", "no es un email de alerta reconocido")


def test_other_fixed_reasons_stay_exactly_as_they_are(conn, no_network):
    old = (EMAILS / "2021-03-10_nuevo-piso_viviendas-tu-zona-personalizada_93231141.eml").read_bytes()
    texty = with_text_part(fixture(DROP_NAME), "text-part-1")
    out_old, out_text = store(conn, [old, texty])
    assert (out_old.outcome, out_old.reason) == ("rejected", "tipo de alerta no soportado")
    assert (out_text.outcome, out_text.reason) == ("failed", "formato sin muestra")
