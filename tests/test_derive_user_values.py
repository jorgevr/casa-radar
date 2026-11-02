"""Derivation must protect values the user entered (FR-011, FR-023, research R11, data-model § Flag texts).

A field whose origin in `listings.field_sources` is `manual` or `csv` is never written by an alert; a
differing alert value raises the flag `la alerta dice <valor> (<fecha>)` in `listings.alert_flags`.
Flag formats follow data-model § Flag texts: dates `dd/mm/aaaa`, money `645.000 €`, area `150 m²`.
All values below are written by hand from the scenarios in spec.md (edge case "Alert contradicts a value
the user entered", FR-023); none comes from running the code.
"""
import json

import pytest

from app import derive, zones
from app.listings import upsert_listing
from app.providers import csv_import


@pytest.fixture(autouse=True)
def no_aliases(tmp_path, monkeypatch):
    monkeypatch.setattr(zones, "ALIASES_PATH", tmp_path / "zone_aliases.yaml")


def _sighting(conn, email_id, listing_id, seen_at, alert_type="new_listing", **fields):
    """Insert an alert sighting for a listing id (the user's listing and the alert share the id)."""
    conn.execute("INSERT INTO alert_emails(email_id, origin, alert_date, alert_type, outcome) "
                 "VALUES(?, 'file', ?, ?, 'imported')", (email_id, seen_at, alert_type))
    row = {"email_id": email_id, "listing_id": listing_id, "alert_type": alert_type, "seen_at": seen_at,
           "development": 0, "link_tracking": "https://www.idealista.com/inmueble/1/?x=1",
           "link_direct": "https://www.idealista.com/inmueble/1/", **fields}
    conn.execute(f"INSERT INTO sightings({','.join(row)}) VALUES({','.join('?' * len(row))})", list(row.values()))


def _user_listing(conn, needs, source, **cols):
    header = ",".join(["id", "url", "property_type", "municipality", *cols])
    line = ",".join(["9001", "https://example.test/9001", "piso", "Getafe", *(str(v) for v in cols.values())])
    ids = csv_import.import_csv_text(conn, f"{header}\n{line}\n", needs, source=source)
    assert len(ids) == 1
    return ids[0]


def _row(conn, lid):
    return conn.execute("SELECT * FROM listings WHERE id=?", (lid,)).fetchone()


def _flags(conn, lid):
    raw = _row(conn, lid)["alert_flags"]
    return json.loads(raw) if raw else []


def _sources(conn, lid):
    raw = _row(conn, lid)["field_sources"]
    return json.loads(raw) if raw else {}


# ── field_sources records where each written field came from (T027) ──────────────────────────────
@pytest.mark.parametrize("source, origin", [("manual", "manual"), ("csv", "csv"), ("idealista", "idealista_api")])
def test_upsert_records_field_sources_by_origin(conn, needs, source, origin):
    # Hand-written input: price 500000, area 142, bedrooms 3 are given; bathrooms, plot_m2 are not.
    raw = {"id": "9001", "url": "https://example.test/9001", "property_type": "piso", "municipality": "Getafe",
           "price": 500000, "area_m2": 142, "bedrooms": 3}
    lid = upsert_listing(conn, raw, source, needs)
    sources = _sources(conn, lid)
    for field in ("price", "area_m2", "bedrooms"):
        assert sources.get(field) == origin, field
    # Only non-null fields are recorded: absent attributes have no origin (FR-011).
    for field in ("bathrooms", "plot_m2", "lat", "lon"):
        assert field not in sources, field


def test_csv_import_records_csv_origin(conn, needs):
    lid = _user_listing(conn, needs, "csv", price=500000, area_m2=142)
    assert _sources(conn, lid)["area_m2"] == "csv"
    assert _sources(conn, lid)["price"] == "csv"


# ── FR-023: user area vs alert area ───────────────────────────────────────────────────────────────
def test_alert_area_differs_from_csv_area_user_value_stays_and_is_flagged(conn, needs, no_network):
    lid = _user_listing(conn, needs, "csv", price=500000, area_m2=142)
    # Alert of 27 Oct 2026 states 150 m² and the same price (no price difference, so no price flag).
    _sighting(conn, "<a@x>", lid, "2026-10-27T19:48:40+01:00", price=500000, area_m2=150)
    derive.derive_listing(conn, lid)
    row = _row(conn, lid)
    assert row["area_m2"] == 142
    assert row["price"] == 500000
    assert _flags(conn, lid) == ["la alerta dice 150 m² (27/10/2026)"]
    # the alert's value is kept with its sighting (FR-023)
    assert conn.execute("SELECT area_m2 FROM sightings WHERE listing_id=?", (lid,)).fetchone()[0] == 150
    # the origin is not overwritten by the alert
    assert _sources(conn, lid)["area_m2"] == "csv"


def test_rederiving_does_not_duplicate_the_flag(conn, needs, no_network):
    lid = _user_listing(conn, needs, "csv", area_m2=142)
    _sighting(conn, "<a@x>", lid, "2026-10-27T19:48:40+01:00", price=500000, area_m2=150)
    derive.derive_listing(conn, lid)
    derive.derive_listing(conn, lid)
    assert _flags(conn, lid) == ["la alerta dice 150 m² (27/10/2026)"]


def test_alert_with_same_value_as_user_raises_no_flag(conn, needs, no_network):
    lid = _user_listing(conn, needs, "csv", area_m2=142)
    _sighting(conn, "<a@x>", lid, "2026-10-27T19:48:40+01:00", area_m2=142)
    derive.derive_listing(conn, lid)
    assert _row(conn, lid)["area_m2"] == 142
    assert _flags(conn, lid) == []


def test_alert_fills_a_field_the_user_left_unknown(conn, needs, no_network):
    # The protection is per field: only fields with a manual/csv origin are protected.
    lid = _user_listing(conn, needs, "csv", price=500000)  # no area given -> unknown, no origin
    _sighting(conn, "<a@x>", lid, "2026-10-27T19:48:40+01:00", price=500000, area_m2=150)
    derive.derive_listing(conn, lid)
    assert _row(conn, lid)["area_m2"] == 150
    assert _flags(conn, lid) == []


# ── FR-023: manually entered price is never replaced ──────────────────────────────────────────────
def test_manual_price_is_never_replaced_by_alert_price_and_differing_price_is_flagged(conn, needs, no_network):
    lid = _user_listing(conn, needs, "manual", price=700000)
    # Alert of 26 Oct 2026 states 645.000 €. Money text per data-model: `645.000 €` (dot thousands).
    _sighting(conn, "<p1@x>", lid, "2026-10-26T10:00:00+01:00", price=645000)
    derive.derive_listing(conn, lid)
    assert _row(conn, lid)["price"] == 700000
    assert _flags(conn, lid) == ["la alerta dice 645.000 € (26/10/2026)"]
    assert _sources(conn, lid)["price"] == "manual"


def test_manual_price_survives_later_and_lower_alert_prices(conn, needs, no_network):
    lid = _user_listing(conn, needs, "manual", price=700000)
    _sighting(conn, "<p1@x>", lid, "2026-10-26T10:00:00+01:00", price=645000)
    _sighting(conn, "<p2@x>", lid, "2026-10-28T10:00:00+01:00", alert_type="price_drop",
              price=630000, previous_price=645000)
    derive.derive_listing(conn, lid)
    assert _row(conn, lid)["price"] == 700000
    # The current alert price (latest sighting, 28 Oct: 630.000) is what differs from the user's price.
    assert "la alerta dice 630.000 € (28/10/2026)" in _flags(conn, lid)


def test_csv_price_is_never_replaced_by_alert_price(conn, needs, no_network):
    lid = _user_listing(conn, needs, "csv", price=700000)
    _sighting(conn, "<p1@x>", lid, "2026-10-26T10:00:00+01:00", price=645000)
    derive.derive_listing(conn, lid)
    assert _row(conn, lid)["price"] == 700000
    assert _flags(conn, lid) == ["la alerta dice 645.000 € (26/10/2026)"]


# ── FR-011: an alert never writes null over a known value ─────────────────────────────────────────
def test_alert_without_values_never_nulls_user_values(conn, needs, no_network):
    lid = _user_listing(conn, needs, "csv", price=500000, area_m2=142, bedrooms=3)
    # Sighting states nothing about price, area or bedrooms (all null).
    _sighting(conn, "<n@x>", lid, "2026-10-27T10:00:00+01:00")
    derive.derive_listing(conn, lid)
    row = _row(conn, lid)
    assert (row["price"], row["area_m2"], row["bedrooms"]) == (500000, 142, 3)
    assert _flags(conn, lid) == []  # a missing value is not a "different" value


def test_later_alert_without_price_does_not_null_an_earlier_alert_price(conn, no_network):
    # Alert-only listing: the earlier alert states 560.000 and 175 m²; the later alert omits both.
    lid = "idealista:777"
    _sighting(conn, "<e1@x>", lid, "2026-10-20T10:00:00+01:00", price=560000, area_m2=175)
    derive.derive_listing(conn, lid)
    _sighting(conn, "<e2@x>", lid, "2026-10-27T10:00:00+01:00")
    derive.derive_listing(conn, lid)
    row = _row(conn, lid)
    assert (row["price"], row["area_m2"]) == (560000, 175)
