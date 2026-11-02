"""Regression tests for the T026/T027 review (specs/001-alert-email-import/reviews/T026.md, findings 1-3).

FR-011: an alert that lacks a field must not erase a value known from another source (url, title,
municipality, district, zone_id included). FR-007/FR-023/FR-036: when the price is user-owned
(`field_sources.price` manual/csv) an alert neither moves `price_updated_at` nor adds alert rows to the
price history. data-model § Extended: listings, `field_sources`: the origin of a value is where it came from.
All values are written by hand from the scenarios in the spec; none comes from running the code.
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
    conn.execute("INSERT INTO alert_emails(email_id, origin, alert_date, alert_type, outcome) "
                 "VALUES(?, 'file', ?, ?, 'imported')", (email_id, seen_at, alert_type))
    row = {"email_id": email_id, "listing_id": listing_id, "alert_type": alert_type, "seen_at": seen_at,
           "development": 0, "link_tracking": "https://www.idealista.com/inmueble/9001/?x=1",
           "link_direct": None, **fields}
    conn.execute(f"INSERT INTO sightings({','.join(row)}) VALUES({','.join('?' * len(row))})", list(row.values()))


def _row(conn, lid):
    return conn.execute("SELECT * FROM listings WHERE id=?", (lid,)).fetchone()


def _sources(conn, lid):
    raw = _row(conn, lid)["field_sources"]
    return json.loads(raw) if raw else {}


def _history(conn, lid):
    return conn.execute("SELECT day, price, origin FROM price_history WHERE listing_id=? ORDER BY rowid",
                        (lid,)).fetchall()


def _api_listing(conn, needs, **extra):
    raw = {"id": "9001", "url": "https://www.idealista.com/inmueble/9001/", "title": "Piso en Getafe",
           "property_type": "piso", "municipality": "Getafe", "district": "Centro", **extra}
    return upsert_listing(conn, raw, "idealista", needs)


# -- finding 1: FR-011, never null over a known value -----------------------------------------------
def test_sighting_without_link_or_matching_location_keeps_known_identity_fields(conn, needs, no_network):
    lid = _api_listing(conn, needs)
    assert lid == "idealista:9001"  # the alert and the API listing share the id
    before = _row(conn, lid)
    known = {c: before[c] for c in ("url", "title", "municipality", "district", "zone_id")}
    # sanity of the hand-written setup: the five values are known before the alert
    assert known["url"] == "https://www.idealista.com/inmueble/9001/"
    assert known["title"] == "Piso en Getafe"
    assert known["municipality"] == "Getafe" and known["district"] == "Centro"
    assert known["zone_id"] == "getafe"  # zone_for: municipality slug (Getafe is not district-level)
    # 27 Oct alert: no direct link (link_direct None), location text that matches no zone
    _sighting(conn, "<a@x>", lid, "2026-10-27T19:48:40+01:00", price=300000,
              type_text="Piso", location_text="Urbanizacion Inventada Sin Zona")
    derive.derive_listing(conn, lid)
    after = _row(conn, lid)
    for col, value in known.items():
        assert after[col] is not None, f"{col} was erased by an alert that did not state it"
        assert after[col] == value, col


def test_sighting_without_type_or_location_text_does_not_null_the_title(conn, needs, no_network):
    lid = _api_listing(conn, needs)
    # 27 Oct alert states only a price: no type_text, no location_text
    _sighting(conn, "<b@x>", lid, "2026-10-27T19:48:40+01:00", price=300000)
    derive.derive_listing(conn, lid)
    assert _row(conn, lid)["title"] == "Piso en Getafe"


# -- finding 2: FR-007 / FR-023 / FR-036, a user-owned price is not touched by alert prices ---------
def _csv_listing(conn, needs, price):
    ids = csv_import.import_csv_text(
        conn, f"id,url,property_type,municipality,price\n9001,https://example.test/9001,piso,Getafe,{price}\n",
        needs, source="csv")
    return ids[0]


def _manual_listing(conn, needs, price):
    return upsert_listing(conn, {"id": "9001", "url": "https://example.test/9001", "property_type": "piso",
                                 "municipality": "Getafe", "price": price}, "manual", needs)


@pytest.mark.parametrize("make", [_manual_listing, _csv_listing], ids=["manual", "csv"])
def test_alert_prices_do_not_touch_a_user_owned_price(conn, needs, no_network, make):
    lid = make(conn, needs, 700000)
    assert _row(conn, lid)["price"] == 700000
    assert _row(conn, lid)["price_updated_at"] is None  # nothing but the user has set the price
    user_history = _history(conn, lid)
    # 26 Oct: alert at 645.000. 28 Oct: price-drop alert 645.000 -> 630.000.
    _sighting(conn, "<a@x>", lid, "2026-10-26T10:00:00+01:00", price=645000)
    _sighting(conn, "<b@x>", lid, "2026-10-28T10:00:00+01:00", alert_type="price_drop",
              price=630000, previous_price=645000)
    derive.derive_listing(conn, lid)
    row = _row(conn, lid)
    assert row["price"] == 700000
    # FR-036: price_updated_at is the alert that changed the listing's price; no alert changed it.
    assert row["price_updated_at"] is None
    # data-model § price_history: alert rows describe the alert price series, which here is not the
    # listing's price; the user's own rows must be the only ones, unchanged.
    # (Ambiguity: docs say alert rows are rebuilt for "alert listings"; a user-owned price is read as not one.)
    assert [tuple(r) for r in _history(conn, lid)] == [tuple(r) for r in user_history]
    assert not [r for r in _history(conn, lid) if r["origin"] in ("alert", "alert_previous")]


# -- finding 3: field_sources records where a value came from --------------------------------------
def test_area_from_idealista_api_keeps_its_origin_when_alerts_do_not_state_it(conn, needs, no_network):
    lid = _api_listing(conn, needs, area_m2=142)
    assert _sources(conn, lid)["area_m2"] == "idealista_api"
    _sighting(conn, "<a@x>", lid, "2026-10-27T19:48:40+01:00", price=300000)  # no area stated
    derive.derive_listing(conn, lid)
    assert _row(conn, lid)["area_m2"] == 142  # kept (FR-011)
    assert _sources(conn, lid)["area_m2"] == "idealista_api"  # not relabelled 'alert'


def test_area_stated_by_an_alert_on_an_alert_listing_is_labelled_alert(conn, needs, no_network):
    lid = "idealista:9002"  # no listing exists: derivation creates it from the sighting alone
    _sighting(conn, "<a@x>", lid, "2026-10-27T19:48:40+01:00", price=300000, area_m2=95)
    derive.derive_listing(conn, lid)
    assert _row(conn, lid)["area_m2"] == 95
    assert _sources(conn, lid)["area_m2"] == "alert"
