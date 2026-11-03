"""new_build is protected like every other user value (review T026-r3, research R11, FR-023, FR-033).

A listing entered by CSV or manually has `field_sources.new_build` = csv/manual (T027) but no
`new_build_origin`. An alert stating new-build must neither overwrite it, nor change its origin labels;
a differing alert value is flagged as `la alerta dice sí (dd/mm/aaaa)` (data-model § Flag texts; booleans
are shown sí/no like exterior/elevator/garage). An alert that does not state new-build never writes
over a stored value (`new_build_stated` is never 0 from absence, data-model).
All expected values are written by hand from those rules; none comes from running the code.
"""
import json

import pytest

from app import derive, zones
from app.listings import upsert_listing


@pytest.fixture(autouse=True)
def no_aliases(tmp_path, monkeypatch):
    monkeypatch.setattr(zones, "ALIASES_PATH", tmp_path / "zone_aliases.yaml")


def _sighting(conn, email_id, listing_id, seen_at, alert_type="new_listing", **fields):
    conn.execute("INSERT INTO alert_emails(email_id, origin, alert_date, alert_type, outcome) "
                 "VALUES(?, 'file', ?, ?, 'imported')", (email_id, seen_at, alert_type))
    row = {"email_id": email_id, "listing_id": listing_id, "alert_type": alert_type, "seen_at": seen_at,
           "development": 0, "link_tracking": "https://www.idealista.com/inmueble/9001/?x=1",
           "link_direct": None, **fields}
    conn.execute(f"INSERT INTO sightings({','.join(row)}) VALUES({','.join('?' * len(row))})", list(row.values()))


def _row(conn, lid):
    return conn.execute("SELECT * FROM listings WHERE id=?", (lid,)).fetchone()


def _flags(conn, lid):
    raw = _row(conn, lid)["alert_flags"]
    return json.loads(raw) if raw else []


def _sources(conn, lid):
    raw = _row(conn, lid)["field_sources"]
    return json.loads(raw) if raw else {}


def _user_listing(conn, needs, source, new_build):
    raw = {"id": "9001", "url": "https://example.test/9001", "property_type": "piso",
           "municipality": "Getafe", "new_build": new_build}
    return upsert_listing(conn, raw, source, needs)


@pytest.mark.parametrize("source", ["csv", "manual"])
def test_alert_stating_new_build_does_not_overwrite_user_zero(conn, needs, no_network, source):
    lid = _user_listing(conn, needs, source, 0)
    # setup sanity: the user's 0 is stored, labelled with its origin, and has no new_build_origin
    assert _row(conn, lid)["new_build"] == 0
    assert _sources(conn, lid)["new_build"] == source
    assert _row(conn, lid)["new_build_origin"] is None
    _sighting(conn, "<a@x>", lid, "2026-10-27T19:48:40+01:00", new_build_stated=1)
    derive.derive_listing(conn, lid)
    row = _row(conn, lid)
    assert row["new_build"] == 0                      # the user's value is kept (FR-023)
    assert row["new_build_origin"] is None            # not relabelled 'email'
    assert _sources(conn, lid)["new_build"] == source  # label unchanged
    # 27 Oct 2026 -> 27/10/2026; the alert states yes -> 'sí' (not '1')
    assert _flags(conn, lid) == ["la alerta dice sí (27/10/2026)"]


@pytest.mark.parametrize("source", ["csv", "manual"])
def test_alert_without_new_build_never_writes_over_user_one(conn, needs, no_network, source):
    lid = _user_listing(conn, needs, source, 1)
    assert _row(conn, lid)["new_build"] == 1
    _sighting(conn, "<b@x>", lid, "2026-10-27T19:48:40+01:00", new_build_stated=None)
    derive.derive_listing(conn, lid)
    row = _row(conn, lid)
    assert row["new_build"] == 1                      # absence is not a value (Article I)
    assert row["new_build_origin"] is None
    assert _sources(conn, lid)["new_build"] == source
    assert _flags(conn, lid) == []                    # nothing differs: nothing stated


@pytest.mark.parametrize("source", ["csv", "manual"])
def test_alert_stating_new_build_matches_user_one_no_flag(conn, needs, no_network, source):
    lid = _user_listing(conn, needs, source, 1)
    _sighting(conn, "<c@x>", lid, "2026-10-27T19:48:40+01:00", new_build_stated=1)
    derive.derive_listing(conn, lid)
    row = _row(conn, lid)
    assert row["new_build"] == 1
    assert _sources(conn, lid)["new_build"] == source  # still the user's
    assert _flags(conn, lid) == []                    # the alert agrees: no flag


def test_alert_created_listing_gets_new_build_from_email(conn, needs, no_network):
    # Guard: no user value exists, so the alert's statement is stored with origin 'email' (FR-033).
    lid = "idealista:777"
    _sighting(conn, "<d@x>", lid, "2026-10-27T19:48:40+01:00", new_build_stated=1)
    derive.derive_listing(conn, lid)
    row = _row(conn, lid)
    assert row["new_build"] == 1
    assert row["new_build_origin"] == "email"
    assert _flags(conn, lid) == []


def test_new_build_origin_user_is_never_changed(conn, needs, no_network):
    # Guard: data-model § Extended: a user value (new_build_origin = user) is never changed.
    lid = _user_listing(conn, needs, "manual", 0)
    conn.execute("UPDATE listings SET new_build_origin='user' WHERE id=?", (lid,))
    _sighting(conn, "<e@x>", lid, "2026-10-27T19:48:40+01:00", new_build_stated=1)
    derive.derive_listing(conn, lid)
    row = _row(conn, lid)
    assert row["new_build"] == 0
    assert row["new_build_origin"] == "user"
