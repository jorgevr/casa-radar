"""Regression tests for T026 review round 2 (specs/001-alert-email-import/reviews/T026-r2.md, findings 1-3).

R11 / Article VIII: a listing is a pure function of its sightings, so the order emails were processed in,
and the history of the database, must not change the result. Where the newest sighting does not state a
value, the value comes from the latest earlier sighting that does (the stored row is only a last resort).
A listing derived before `field_sources` existed (NULL) is re-derived like a fresh one.
data-model § Extended: listings, `field_sources`: the origin of a value is where it came from.
All expected values are written by hand from the scenarios below; none comes from running the code.
"""
import json

import pytest

from app import db, derive, zones
from app.etl import indicators as ind_etl
from app.listings import upsert_listing

L = "idealista:9001"
LINK_A = "https://www.idealista.com/inmueble/9001/"
LINK_C = "https://www.idealista.com/inmueble/9001/new"
COLS = ("url", "title", "municipality", "district", "zone_id", "location_text")


@pytest.fixture(autouse=True)
def no_aliases(tmp_path, monkeypatch):
    monkeypatch.setattr(zones, "ALIASES_PATH", tmp_path / "zone_aliases.yaml")


def _fresh():
    c = db.connect(":memory:")
    ind_etl.seed_madrid_districts(c)
    return c


def _sighting(conn, email_id, seen_at, alert_type="new_listing", **fields):
    conn.execute("INSERT INTO alert_emails(email_id, origin, alert_date, alert_type, outcome) "
                 "VALUES(?, 'file', ?, ?, 'imported')", (email_id, seen_at, alert_type))
    row = {"email_id": email_id, "listing_id": L, "alert_type": alert_type, "seen_at": seen_at,
           "development": 0, "link_tracking": "https://www.idealista.com/inmueble/9001/?x=1",
           "link_direct": None, **fields}
    conn.execute(f"INSERT INTO sightings({','.join(row)}) VALUES({','.join('?' * len(row))})", list(row.values()))


def _add(conn, s):
    s = dict(s)
    _sighting(conn, s.pop("email_id"), s.pop("seen_at"), **s)


def _row(conn):
    return conn.execute("SELECT * FROM listings WHERE id=?", (L,)).fetchone()


def _view(conn):
    r = _row(conn)
    return {c: r[c] for c in COLS}


def _sources(conn):
    raw = _row(conn)["field_sources"]
    return json.loads(raw) if raw else {}


# 23 Oct: older sighting. Has the direct link and a location text that resolves to Getafe.
A = dict(email_id="<a@x>", seen_at="2026-10-23T10:00:00+02:00", price=670000, type_text="Piso",
         location_text="Getafe", link_direct=LINK_A)
# 26 Oct: newer sighting. No direct link, location text no zone resolves.
B = dict(email_id="<b@x>", seen_at="2026-10-26T10:00:00+01:00", price=645000, type_text="Piso",
         location_text="Urbanizacion Inventada Sin Zona")
# 28 Oct: newest sighting. States only a price: no type, no location text, no link.
N = dict(email_id="<n@x>", seen_at="2026-10-28T10:00:00+01:00", price=640000)
# 28 Oct: a newer alert with a different type, the same location and another direct link.
C = dict(email_id="<c@x>", seen_at="2026-10-28T10:00:00+01:00", price=640000, type_text="Atico",
         location_text="Getafe", link_direct=LINK_C)


def _derive_in_order(sightings, twice=False):
    c = _fresh()
    for s in sightings:
        _add(c, s)
        derive.derive_listing(c, L)
    if twice:
        derive.derive_listing(c, L)
    return c


# -- finding 1: order independence -------------------------------------------------------------------
def test_url_and_zone_come_from_the_latest_sighting_that_states_them_in_either_order(no_network):
    # Expected by hand: url = A's link (the only sighting with one); municipality/district/zone from the
    # latest location text that RESOLVES a zone: A's "Getafe" -> municipality "Getafe", no district,
    # zone_id "getafe" (slug of the municipality, zones.match_zone). B's text resolves nothing.
    expected_geo = {"url": LINK_A, "municipality": "Getafe", "district": None, "zone_id": "getafe"}
    results = {}
    for name, order, twice in (("AB", (A, B), False), ("BA", (B, A), False),
                               ("AB twice", (A, B), True), ("BA twice", (B, A), True)):
        view = _view(_derive_in_order(order, twice))
        results[name] = view
        for col, value in expected_geo.items():
            assert view[col] == value, f"order {name}: {col}"
    assert results["AB"] == results["BA"] == results["AB twice"] == results["BA twice"]


def test_newest_sighting_without_type_or_location_keeps_title_from_latest_that_has_them(no_network):
    # N (newest) states only a price. Title text comes from the latest sightings that state them:
    # type "Piso" (B), location text "Urbanizacion Inventada Sin Zona" (B) -> "Piso en Urbanizacion ...".
    # url stays A's link; zone stays Getafe (latest resolving text). Same for every order.
    expected = {"url": LINK_A, "title": "Piso en Urbanizacion Inventada Sin Zona", "municipality": "Getafe",
                "district": None, "zone_id": "getafe", "location_text": "Urbanizacion Inventada Sin Zona"}
    for order in ((A, B, N), (N, B, A), (B, N, A), (N, A, B)):
        assert _view(_derive_in_order(order)) == expected, [s["email_id"] for s in order]


def test_newest_sighting_without_type_keeps_type_from_an_earlier_one(no_network):
    # A states type "Piso" and a link only; the newer one states location "Getafe" but no type:
    # title is "Piso en Getafe", url is A's link, in either order.
    a_typed = {k: v for k, v in A.items() if k != "location_text"}
    newer = dict(email_id="<d@x>", seen_at="2026-10-27T10:00:00+01:00", price=640000, location_text="Getafe")
    for order in ((a_typed, newer), (newer, a_typed)):
        view = _view(_derive_in_order(order))
        assert view["title"] == "Piso en Getafe"
        assert view["url"] == LINK_A


# -- finding 2: a listing derived before field_sources existed is re-derived like a fresh one ---------
def _legacy_listing(conn, sources=None, **over):
    """A listing row as the Phase 3 derivation left it: field_sources NULL (or as given)."""
    zones.match_zone("Getafe", conn)  # makes the zone row the listing points to
    row = {"id": L, "source": "idealista", "url": LINK_A, "title": "Piso en Getafe", "property_type": "piso",
           "price": 670000, "municipality": "Getafe", "district": None, "zone_id": "getafe",
           "location_text": "Getafe", "first_seen": "2026-10-23", "last_seen": "2026-10-23",
           "field_sources": None if sources is None else json.dumps(sources), **over}
    conn.execute(f"INSERT INTO listings({','.join(row)}) VALUES({','.join('?' * len(row))})", list(row.values()))


def test_legacy_listing_without_field_sources_takes_newer_title_and_url(no_network):
    # Fresh database, same two sightings (A then C): newest type "Atico", location "Getafe", latest
    # direct link C's -> title "Atico en Getafe", url LINK_C.
    fresh = _derive_in_order((A, C))
    assert _view(fresh)["title"] == "Atico en Getafe" and _view(fresh)["url"] == LINK_C
    legacy = _fresh()
    _legacy_listing(legacy)
    _add(legacy, A)
    _add(legacy, C)
    derive.derive_listing(legacy, L)
    derive.derive_listing(legacy, L)  # idempotent
    view = _view(legacy)
    assert view["title"] == "Atico en Getafe"
    assert view["url"] == LINK_C
    assert view == _view(fresh)


@pytest.mark.parametrize("origin", ["idealista_api", "manual", "csv"])
def test_url_and_title_with_a_recorded_non_alert_origin_are_not_replaced(no_network, origin):
    conn = _fresh()
    _legacy_listing(conn, sources={"url": origin, "title": origin}, url="https://example.test/own",
                    title="Mi titulo")
    _add(conn, C)
    derive.derive_listing(conn, L)
    row = _row(conn)
    assert row["url"] == "https://example.test/own"
    assert row["title"] == "Mi titulo"
    assert _sources(conn)["url"] == origin and _sources(conn)["title"] == origin


# -- finding 3: the zone trio's origin label follows the value ---------------------------------------
def test_zone_trio_overwritten_by_an_alert_is_labelled_alert(conn, needs, no_network):
    lid = upsert_listing(conn, {"id": "9001", "url": LINK_A, "title": "Piso en Getafe", "property_type": "piso",
                                "municipality": "Getafe", "district": "Centro"}, "idealista", needs)
    assert lid == L
    assert _sources_of(conn, lid)["municipality"] == "idealista_api"  # sanity of the setup
    # 27 Oct alert in Torrejon de Ardoz: a municipality zones.match_zone resolves (zone "torrejon-de-ardoz")
    conn.execute("INSERT INTO alert_emails(email_id, origin, alert_date, alert_type, outcome) "
                 "VALUES('<z@x>', 'file', '2026-10-27', 'new_listing', 'imported')")
    conn.execute("INSERT INTO sightings(email_id, listing_id, alert_type, seen_at, development, link_tracking, "
                 "price, type_text, location_text) VALUES('<z@x>', ?, 'new_listing', '2026-10-27T10:00:00+01:00', "
                 "0, 'https://www.idealista.com/inmueble/9001/?x=1', 300000, 'Piso', 'Torrejón de Ardoz')",
                 (lid,))
    derive.derive_listing(conn, lid)
    row = conn.execute("SELECT * FROM listings WHERE id=?", (lid,)).fetchone()
    assert row["zone_id"] == "torrejon-de-ardoz"  # precondition: the alert's zone replaced the API's
    src = _sources_of(conn, lid)
    assert src["municipality"] == "alert"
    assert src["zone_id"] == "alert"
    # field_sources records only non-null fields (data-model, T027): the alert gives no district, so the
    # district is never labelled 'alert'. Either it is cleared with the zone (label absent) or the stored
    # value is kept with its original label (FR-011).
    assert src.get("district") != "alert"
    if row["district"] is not None:
        assert src.get("district") == "idealista_api"
    else:
        assert "district" not in src


def _sources_of(conn, lid):
    raw = conn.execute("SELECT field_sources FROM listings WHERE id=?", (lid,)).fetchone()[0]
    return json.loads(raw) if raw else {}
