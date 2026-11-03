"""Marking a listing "no longer available" and the relisted flag (T066, US2; FR-019, spec edge case "Relisted").

Implemented by T067 (PATCH + scoring flag + ordering) and T068 (derive relisted flag).

Expected values are fixed by the task text, spec.md FR-019 and data-model.md (§ Flag texts), not by the
code's output:
- `ya no disponible` is the exact flag of a listing with availability `gone`.
- `vuelto a ver en una alerta el <fecha>` (dd/mm/aaaa) appears only for a `gone` listing that has a
  sighting dated AFTER the mark (availability_changed_at); the listing stays `gone`.
- The mark date is controlled by monkeypatching `app.db.today` (the code base's only "today"; also
  `app.main.today` in case T067 imports the name). Dates below are chosen by hand:
  fixture sighting 2026-10-23 < mark 2026-10-24 < synthetic later sighting 2026-10-25, and an earlier
  synthetic sighting 2026-10-20 < mark.
- Ranking: with the example needs and the fixtures below, idealista:112887282 and :112899473 score 50.0
  (top) among the non-excluded listings, which is why marking 112887282 `gone` must move it behind the
  other non-excluded listings (T067: gone after active, not excluded).
"""
import base64
import json
import sqlite3

import pytest
from fastapi.testclient import TestClient

from app import db, derive, zones
from app import main as main_module
from app.main import create_app

from .conftest import EMAILS, EXAMPLE_NEEDS

TARGET_FILE = "2026-10-23_nuevo-chalet-independiente_viviendas-en-tu-zona-personalizada_112887282.eml"
TARGET = "idealista:112887282"  # id contains a colon; the PATCH route is {lid:path}
OTHER_FILES = sorted(p.name for p in EMAILS.glob("2026-*.eml") if p.name != TARGET_FILE)

MARK_DAY = "2026-10-24"          # the fixture's sighting is dated 2026-10-23, before the mark
LATER_SEEN = "2026-10-25T10:00:00+02:00"
EARLIER_SEEN = "2026-10-20T10:00:00+02:00"

GONE_FLAG = "ya no disponible"
RELISTED_25 = "vuelto a ver en una alerta el 25/10/2026"


@pytest.fixture(autouse=True)
def no_aliases(tmp_path, monkeypatch):
    monkeypatch.setattr(zones, "ALIASES_PATH", tmp_path / "zone_aliases.yaml")


@pytest.fixture
def db_file(tmp_path):
    return str(tmp_path / "t.db")


@pytest.fixture
def client(tmp_path, db_file):
    needs = tmp_path / "needs.yaml"
    needs.write_text(EXAMPLE_NEEDS.read_text(encoding="utf-8"), encoding="utf-8")
    # context manager so the event loop exists before `no_network` is applied: list `client` before it
    with TestClient(create_app(db_file, str(needs))) as c:
        yield c


@pytest.fixture
def today(monkeypatch):
    """Control the day the mark is stamped with; returns a setter."""
    state = {"day": MARK_DAY}
    monkeypatch.setattr(db, "today", lambda: state["day"])
    monkeypatch.setattr(main_module, "today", lambda: state["day"], raising=False)

    def set_day(day):
        state["day"] = day

    return set_day


def _import(client, names):
    files = [{"name": n, "content_base64": base64.b64encode((EMAILS / n).read_bytes()).decode("ascii")}
             for n in names]
    resp = client.post("/api/alerts/import", json={"files": files})
    assert resp.status_code == 200, resp.text
    assert resp.json()["n_failed"] == 0 and resp.json()["n_rejected"] == 0
    return resp.json()


def _listings(client):
    resp = client.get("/api/listings")
    assert resp.status_code == 200, resp.text
    return resp.json()


def _get(client, lid):
    found = [x for x in _listings(client) if x["id"] == lid]
    assert len(found) == 1, f"{lid} not returned by GET /api/listings"
    return found[0]


def _patch(client, lid, body):
    return client.patch(f"/api/listings/{lid}", json=body)


def _mark(client, availability):
    resp = _patch(client, TARGET, {"availability": availability})
    assert resp.status_code == 200, resp.text


def _add_sighting(db_file, listing_id, seen_at, tag):
    """A synthetic sighting: a copy of the listing's existing sighting (so price and attributes do not
    change) with a new email id and `seen_at`, then re-derived by the app's own derive.derive_listing."""
    conn = db.connect(db_file)
    try:
        row = dict(conn.execute("SELECT * FROM sightings WHERE listing_id=? ORDER BY seen_at",
                                (listing_id,)).fetchone())
        row.update(email_id=f"synthetic-{tag}", seen_at=seen_at)
        conn.execute(f"INSERT INTO sightings({','.join(row)}) VALUES({','.join('?' * len(row))})",
                     list(row.values()))
        conn.execute("INSERT INTO alert_emails(email_id, origin, file_name, subject, alert_date, outcome) "
                     "VALUES(?,?,?,?,?,?)",
                     (f"synthetic-{tag}", "file", f"{tag}.eml", f"synthetic {tag}", seen_at, "imported"))
        derive.derive_listing(conn, listing_id)
        conn.commit()
    finally:
        conn.close()


def _stored_alert_flags(db_file, listing_id):
    c = sqlite3.connect(db_file)
    try:
        raw = c.execute("SELECT alert_flags FROM listings WHERE id=?", (listing_id,)).fetchone()[0]
    finally:
        c.close()
    return json.loads(raw) if raw else []


def _relisted(flags):
    return [f for f in flags if f.startswith("vuelto a ver en una alerta el ")]


# ── (1) mark gone ────────────────────────────────────────────────────────────

def test_mark_gone_keeps_listing_with_flag_and_date(client, today, no_network):
    _import(client, [TARGET_FILE])
    before = _get(client, TARGET)
    assert before["availability"] == "active"
    assert GONE_FLAG not in before["eval"]["flags"]

    resp = _patch(client, TARGET, {"availability": "gone"})

    assert resp.status_code == 200, resp.text
    after = _get(client, TARGET)  # still returned, not deleted
    assert after["availability"] == "gone"
    assert after["availability_changed_at"] == MARK_DAY
    assert GONE_FLAG in after["eval"]["flags"]
    assert after["eval"]["excluded"] == []  # not excluded: it stays in the ranking


def test_mark_gone_only_changes_that_listing(client, today, no_network):
    _import(client, [TARGET_FILE, *OTHER_FILES])
    _mark(client, "gone")

    assert _get(client, TARGET)["availability"] == "gone"
    others = [x for x in _listings(client) if x["id"] != TARGET]

    assert len(others) == 10
    assert all(x["availability"] == "active" for x in others)
    assert all(x["availability_changed_at"] is None for x in others)
    assert all(GONE_FLAG not in x["eval"]["flags"] for x in others)


# ── (2) undo ─────────────────────────────────────────────────────────────────

def test_mark_active_undoes_gone(client, today, no_network):
    _import(client, [TARGET_FILE])
    _mark(client, "gone")
    today("2026-10-26")

    resp = _patch(client, TARGET, {"availability": "active"})

    assert resp.status_code == 200, resp.text
    after = _get(client, TARGET)  # still returned
    assert after["availability"] == "active"
    assert GONE_FLAG not in after["eval"]["flags"]
    assert after["availability_changed_at"] == "2026-10-26"  # set to today on every change (T067)


# ── (3) FR-019: absence never changes availability ───────────────────────────

def test_importing_fixtures_without_the_listing_never_changes_availability(client, today, no_network):
    _import(client, [TARGET_FILE])
    _mark(client, "gone")
    today("2026-11-15")  # a later import must not touch availability or its date

    _import(client, OTHER_FILES)  # none of these contains idealista:112887282

    ids = {x["id"] for x in _listings(client)}
    assert len(ids) == 11 and TARGET in ids
    target = _get(client, TARGET)
    assert target["availability"] == "gone"
    assert target["availability_changed_at"] == MARK_DAY
    assert GONE_FLAG in target["eval"]["flags"]
    assert all(x["availability"] == "active" for x in _listings(client) if x["id"] != TARGET)


def test_absence_does_not_mark_anything_gone_on_a_fresh_import(client, no_network):
    # nothing is ever marked by import alone, whatever the later alerts do not mention
    _import(client, [TARGET_FILE])
    _import(client, OTHER_FILES)

    listings = _listings(client)

    assert len(listings) == 11
    assert all(x["availability"] == "active" for x in listings)
    assert all(GONE_FLAG not in x["eval"]["flags"] for x in listings)


# ── (4) Relisted ─────────────────────────────────────────────────────────────

def test_sighting_after_the_mark_keeps_gone_and_adds_relisted_flag(client, db_file, today, no_network):
    _import(client, [TARGET_FILE])
    _mark(client, "gone")

    # baseline: the only sighting (2026-10-23) predates the mark (2026-10-24): no relisted flag
    assert _relisted(_get(client, TARGET)["eval"]["flags"]) == []

    _add_sighting(db_file, TARGET, LATER_SEEN, "after")

    after = _get(client, TARGET)
    assert after["availability"] == "gone"  # only the user changes it
    assert after["availability_changed_at"] == MARK_DAY
    assert GONE_FLAG in after["eval"]["flags"]
    assert RELISTED_25 in after["eval"]["flags"]
    assert RELISTED_25 in _stored_alert_flags(db_file, TARGET)  # derivation writes it to alert_flags


def test_sighting_before_the_mark_adds_no_relisted_flag(client, db_file, today, no_network):
    _import(client, [TARGET_FILE])
    _mark(client, "gone")

    _add_sighting(db_file, TARGET, EARLIER_SEEN, "before")

    after = _get(client, TARGET)
    assert after["availability"] == "gone"
    assert GONE_FLAG in after["eval"]["flags"]
    assert _relisted(after["eval"]["flags"]) == []
    assert _relisted(_stored_alert_flags(db_file, TARGET)) == []


def test_sighting_after_a_date_on_an_active_listing_adds_no_relisted_flag(client, db_file, today, no_network):
    # the relisted flag is only for listings marked gone
    _import(client, [TARGET_FILE])

    _add_sighting(db_file, TARGET, LATER_SEEN, "active")

    after = _get(client, TARGET)
    assert after["availability"] == "active"
    assert _relisted(after["eval"]["flags"]) == []
    assert _relisted(_stored_alert_flags(db_file, TARGET)) == []


# ── (5) invalid value ────────────────────────────────────────────────────────

@pytest.mark.parametrize("value", ["banana", "", "GONE", "Active", None, True, 1, ["gone"]],
                         ids=["word", "empty", "upper", "capitalised", "null", "bool", "int", "list"])
def test_invalid_availability_is_400_and_changes_nothing(client, today, no_network, value):
    _import(client, [TARGET_FILE])

    resp = _patch(client, TARGET, {"availability": value})

    assert resp.status_code == 400, resp.text
    after = _get(client, TARGET)
    assert after["availability"] == "active"
    assert after["availability_changed_at"] is None
    assert GONE_FLAG not in after["eval"]["flags"]


def test_availability_does_not_break_other_patch_fields(client, today, no_network):
    _import(client, [TARGET_FILE])

    resp = _patch(client, TARGET, {"status": "shortlist", "availability": "gone"})

    assert resp.status_code == 200, resp.text
    after = _get(client, TARGET)
    assert after["status"] == "shortlist"
    assert after["availability"] == "gone"


# ── T067: ordering ───────────────────────────────────────────────────────────

def test_gone_listing_sorts_after_active_ones_without_being_excluded(client, today, no_network):
    _import(client, [TARGET_FILE, *OTHER_FILES])
    ranked = _listings(client)
    non_excluded = [x["id"] for x in ranked if not x["eval"]["excluded"]]
    assert non_excluded[0] in (TARGET, "idealista:112899473")  # both score 50.0 (hand-checked above)
    assert TARGET in non_excluded[:2]
    assert len(non_excluded) == 7

    _mark(client, "gone")

    ranked = _listings(client)
    assert len(ranked) == 11  # nothing dropped
    target = next(x for x in ranked if x["id"] == TARGET)
    assert target["eval"]["excluded"] == []
    non_excluded = [x["id"] for x in ranked if not x["eval"]["excluded"]]
    assert len(non_excluded) == 7
    assert non_excluded[-1] == TARGET  # behind every other non-excluded (active) listing
    assert non_excluded[0] == "idealista:112899473"
