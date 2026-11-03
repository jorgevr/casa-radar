"""new_build from the provider API is not user-owned: an alert's statement wins (review T026-r4, data-model).

data-model § Extended listings: new_build = 1 if any sighting states it with origin 'email'; only a user
value (new_build_origin 'user', or field_sources csv/manual) is never changed. A value written by the
Idealista API (field_sources.new_build = 'idealista_api') is NOT a user value, so an alert stating
new-build overrides it, labels it 'alert' / origin 'email', and raises no 'la alerta dice' flag
(there is no user value to disagree with). The flag format for user values is asserted in
tests/test_derive_new_build_protection.py. All expected values are written by hand from those rules.
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


def _listing(conn, needs, source, new_build):
    raw = {"id": "9001", "url": "https://example.test/9001", "property_type": "piso",
           "municipality": "Getafe", "newDevelopment" if source == "idealista" else "new_build": new_build}
    return upsert_listing(conn, raw, source, needs)


def _api_listing(conn, needs, new_build=False):
    lid = _listing(conn, needs, "idealista", new_build)
    # setup sanity: the API's 0 is stored and labelled with the API origin, no email origin yet
    assert _row(conn, lid)["new_build"] == 0
    assert _sources(conn, lid)["new_build"] == "idealista_api"
    assert _row(conn, lid)["new_build_origin"] is None
    return lid


def test_alert_new_build_overrides_api_zero(conn, needs, no_network):
    lid = _api_listing(conn, needs)
    _sighting(conn, "<a@x>", lid, "2026-10-27T19:48:40+01:00", new_build_stated=1)
    derive.derive_listing(conn, lid)
    row = _row(conn, lid)
    assert row["new_build"] == 1                         # the alert states new-build; API value is not a user's
    assert row["new_build_origin"] == "email"
    assert _sources(conn, lid)["new_build"] == "alert"   # the stored value now comes from the alert
    assert _flags(conn, lid) == []                       # no user value to disagree with: no flag


def test_alert_first_then_api_refresh_then_derive_again(conn, needs, no_network):
    lid = _api_listing(conn, needs)
    _sighting(conn, "<b@x>", lid, "2026-10-27T19:48:40+01:00", new_build_stated=1)
    derive.derive_listing(conn, lid)
    assert _row(conn, lid)["new_build"] == 1
    # API refresh writes newDevelopment false again: value 0 and label back to idealista_api
    upsert_listing(conn, {"id": "9001", "url": "https://example.test/9001", "property_type": "piso",
                          "municipality": "Getafe", "newDevelopment": False}, "idealista", needs)
    assert _row(conn, lid)["new_build"] == 0
    assert _sources(conn, lid)["new_build"] == "idealista_api"
    derive.derive_listing(conn, lid)
    row = _row(conn, lid)
    assert row["new_build"] == 1                         # the sighting still states it: derived again
    assert row["new_build_origin"] == "email"            # no stale origin next to a non-email value
    assert _sources(conn, lid)["new_build"] == "alert"
    assert _flags(conn, lid) == []


def test_alert_not_stating_new_build_leaves_api_zero(conn, needs, no_network):
    lid = _api_listing(conn, needs)
    _sighting(conn, "<c@x>", lid, "2026-10-27T19:48:40+01:00", new_build_stated=None)
    derive.derive_listing(conn, lid)
    row = _row(conn, lid)
    assert row["new_build"] == 0                         # absence is not a value (Article I)
    assert row["new_build_origin"] is None
    assert _sources(conn, lid)["new_build"] == "idealista_api"
    assert _flags(conn, lid) == []


@pytest.mark.parametrize("source", ["csv", "manual"])
def test_user_zero_still_protected_and_flagged(conn, needs, no_network, source):
    lid = _listing(conn, needs, source, 0)
    _sighting(conn, "<d@x>", lid, "2026-10-27T19:48:40+01:00", new_build_stated=1)
    derive.derive_listing(conn, lid)
    row = _row(conn, lid)
    assert row["new_build"] == 0
    assert row["new_build_origin"] is None
    assert _sources(conn, lid)["new_build"] == source
    assert _flags(conn, lid) == ["la alerta dice sí (27/10/2026)"]   # 27 Oct 2026, boolean shown sí


def test_origin_user_still_protected(conn, needs, no_network):
    lid = _listing(conn, needs, "manual", 0)
    conn.execute("UPDATE listings SET new_build_origin='user' WHERE id=?", (lid,))
    _sighting(conn, "<e@x>", lid, "2026-10-27T19:48:40+01:00", new_build_stated=1)
    derive.derive_listing(conn, lid)
    row = _row(conn, lid)
    assert row["new_build"] == 0
    assert row["new_build_origin"] == "user"
    assert _flags(conn, lid) == ["la alerta dice sí (27/10/2026)"]
