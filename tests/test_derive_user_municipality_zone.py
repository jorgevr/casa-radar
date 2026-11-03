"""T026 fix loop 6: a user-owned municipality keeps the zone, and the zone's label never depends on order.

R11 / Article VIII: derivation is a pure function of the sightings plus the values the user owns. When the
listing's municipality is user-owned (`field_sources.municipality` is manual or csv), derivation keeps the
user's municipality, district and zone_id. Those two columns must then never be labelled 'alert', whichever
order the emails were processed in (before the fix the label was 'alert' when the kept zone happened to
equal the zone of the latest sighting with a recognised location, so it varied with the order).
All expected values are written by hand from the scenarios below; none comes from running the code.
"""
import json

import pytest

from app import db, derive, zones
from app.etl import indicators as ind_etl
from app.providers import csv_import

# 20 Oct: location text that zones.match_zone resolves to municipality Getafe (zone "getafe").
A = dict(email_id="<a@x>", seen_at="2026-10-20T10:00:00+02:00", price=500000, type_text="Piso",
         location_text="Getafe")
# 27 Oct: location text that resolves to Torrejon de Ardoz (zone "torrejon-de-ardoz").
B = dict(email_id="<b@x>", seen_at="2026-10-27T10:00:00+01:00", price=500000, type_text="Piso",
         location_text="Torrejón de Ardoz")


@pytest.fixture(autouse=True)
def no_aliases(tmp_path, monkeypatch):
    monkeypatch.setattr(zones, "ALIASES_PATH", tmp_path / "zone_aliases.yaml")


def _fresh():
    c = db.connect(":memory:")
    ind_etl.seed_madrid_districts(c)
    return c


def _user_listing(conn, needs, source):
    # The user states Getafe / Centro; the zone_id column is the one upsert_listing derives for it ("getafe").
    csv = ("id,url,property_type,municipality,district,price\n"
           "9001,https://example.test/9001,piso,Getafe,Centro,500000\n")
    ids = csv_import.import_csv_text(conn, csv, needs, source=source)
    assert len(ids) == 1
    return ids[0]


def _add(conn, lid, s):
    s = dict(s)
    email_id, seen_at = s.pop("email_id"), s.pop("seen_at")
    conn.execute("INSERT INTO alert_emails(email_id, origin, alert_date, alert_type, outcome) "
                 "VALUES(?, 'file', ?, 'new_listing', 'imported')", (email_id, seen_at))
    row = {"email_id": email_id, "listing_id": lid, "alert_type": "new_listing", "seen_at": seen_at,
           "development": 0, "link_tracking": "https://www.idealista.com/inmueble/9001/?x=1",
           "link_direct": None, **s}
    conn.execute(f"INSERT INTO sightings({','.join(row)}) VALUES({','.join('?' * len(row))})", list(row.values()))


def _run(needs, source, sightings, each=True):
    """Fresh database, the user's listing, then the sightings in the given order. Returns (row, sources)."""
    c = _fresh()
    lid = _user_listing(c, needs, source)
    for s in sightings:
        _add(c, lid, s)
        if each:
            derive.derive_listing(c, lid)
    if not each:
        derive.derive_listing(c, lid)
    row = c.execute("SELECT * FROM listings WHERE id=?", (lid,)).fetchone()
    sources = json.loads(row["field_sources"]) if row["field_sources"] else {}
    return {k: row[k] for k in row.keys()}, sources


def _check_user_municipality(needs, source, no_network):
    variants = {
        "A then B, derive after each": _run(needs, source, [A, B]),
        "B then A, derive after each": _run(needs, source, [B, A]),
        "A then B, derive once": _run(needs, source, [A, B], each=False),
        "B then A, derive once": _run(needs, source, [B, A], each=False),
        "A only": _run(needs, source, [A]),
    }
    ref_row, ref_sources = variants["A then B, derive after each"]
    # The user's values are kept: Getafe / Centro; zone_id is the one stored for them ("getafe").
    assert ref_row["municipality"] == "Getafe"
    assert ref_row["district"] == "Centro"
    assert ref_row["zone_id"] == "getafe"
    assert ref_sources["municipality"] == source
    for name, (row, sources) in variants.items():
        assert sources.get("zone_id") != "alert", name
        assert sources.get("district") != "alert", name
        assert sources.get("municipality") == source, name
        assert (row["municipality"], row["district"], row["zone_id"]) == ("Getafe", "Centro", "getafe"), name
        if name != "A only":  # same two sightings, so the whole result must match whatever the order
            assert sources == ref_sources, name
            assert row == ref_row, name


def test_manual_municipality_zone_label_is_the_same_for_every_order(needs, no_network):
    _check_user_municipality(needs, "manual", no_network)


def test_csv_municipality_zone_label_is_the_same_for_every_order(needs, no_network):
    _check_user_municipality(needs, "csv", no_network)


def test_control_alert_municipality_zone_is_still_labelled_alert(needs, no_network):
    # Control: with no user-owned municipality the alert's zone is written and labelled 'alert'.
    # Only sighting A exists (Getafe), so zone_id "getafe" and municipality "Getafe" come from the alert.
    c = _fresh()
    lid = "idealista:9001"
    _add(c, lid, A)
    derive.derive_listing(c, lid)
    row = c.execute("SELECT * FROM listings WHERE id=?", (lid,)).fetchone()
    sources = json.loads(row["field_sources"])
    assert row["zone_id"] == "getafe" and row["municipality"] == "Getafe"
    assert sources["zone_id"] == "alert"
    assert sources["municipality"] == "alert"
