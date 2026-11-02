"""Price rules of listing derivation (research R11, FR-006-FR-008, FR-035; data-model § Extended: listings,
price_history and § Flag texts).

Expected values are worked out by hand from the dates and prices written in each test (and, for the real
fixtures, from the sentence "El precio de este anuncio ha bajado de X a Y" and the Date header of the .eml).
Flag texts are the exact Spanish strings of data-model § Flag texts: dates dd/mm/aaaa, money like 645.000 €.
Derivation is a pure function of the sightings, so every case is also run in both processing orders.
"""
import json
import random
from pathlib import Path

import pytest

from app import alerts, db, derive, zones
from app.etl import indicators as ind_etl

EMAILS = Path(__file__).parent / "fixtures" / "emails"
DROP_CODE = "112842548"  # fixture 2026-10-26: "ha bajado de 670.000 € a 645.000 €", Date Mon, 26 Oct 2026 12:28:28 +0100


@pytest.fixture(autouse=True)
def no_aliases(tmp_path, monkeypatch):
    monkeypatch.setattr(zones, "ALIASES_PATH", tmp_path / "zone_aliases.yaml")


def _sighting(conn, email_id, code, seen_at, alert_type="new_listing", **fields):
    conn.execute("INSERT INTO alert_emails(email_id, origin, alert_date, alert_type, outcome) "
                 "VALUES(?, 'file', ?, ?, 'imported')", (email_id, seen_at, alert_type))
    row = {"email_id": email_id, "listing_id": f"idealista:{code}", "alert_type": alert_type,
           "seen_at": seen_at, "development": 0, "link_tracking": f"https://www.idealista.com/inmueble/{code}/?x=1",
           "link_direct": f"https://www.idealista.com/inmueble/{code}/", **fields}
    conn.execute(f"INSERT INTO sightings({','.join(row)}) VALUES({','.join('?' * len(row))})", list(row.values()))
    return row["listing_id"]


def _add(conn, email_id, code, seen_at, price, previous=None):
    """Record one sighting and re-derive its listing (a price drop when `previous` is given)."""
    lid = _sighting(conn, email_id, code, seen_at, "price_drop" if previous else "new_listing",
                    price=price, previous_price=previous, location_text="Getafe")
    derive.derive_listing(conn, lid)
    return lid


def _listing(conn, lid):
    return conn.execute("SELECT * FROM listings WHERE id=?", (lid,)).fetchone()


def _history(conn, lid):
    rows = conn.execute("SELECT day, price, origin FROM price_history WHERE listing_id=? "
                        "ORDER BY day, origin='alert_previous' DESC, rowid", (lid,)).fetchall()
    return [tuple(r) for r in rows]


def _flags(row):
    return json.loads(row["alert_flags"] or "[]")


def _fixture(conn, code):
    raw = next(EMAILS.glob(f"*_{code}.eml")).read_bytes()
    run_id = alerts.start_run(conn, "file_cli")
    out = alerts.process_message(conn, raw, origin="file", file_name=f"{code}.eml", run_id=run_id)
    assert out.outcome == "imported"
    return out


# ── US2-2: a later, lower price updates the price and the history ──
@pytest.mark.parametrize("newest_first", [False, True], ids=["in-order", "newest-processed-first"])
def test_later_lower_price_updates_price_and_history(conn, newest_first):
    # 20 Oct 500.000 then 25 Oct 480.000: current price is the later one, history has both, in date order.
    steps = [("<p1@x>", "2026-10-20T10:00:00+02:00", 500_000), ("<p2@x>", "2026-10-25T10:00:00+02:00", 480_000)]
    for email_id, seen_at, price in (reversed(steps) if newest_first else steps):  # US2-3 / FR-008 when reversed
        lid = _add(conn, email_id, "1001", seen_at, price)
    assert conn.execute("SELECT COUNT(*) FROM listings").fetchone()[0] == 1
    row = _listing(conn, lid)
    assert row["price"] == 480_000
    assert (row["published_at"], row["price_updated_at"]) == ("2026-10-20", "2026-10-25")
    assert (row["first_seen"], row["last_seen"]) == ("2026-10-20", "2026-10-25")
    assert _history(conn, lid) == [("2026-10-20", 500_000, "alert"), ("2026-10-25", 480_000, "alert")]
    assert _flags(row) == []


# ── US2-3 / FR-008: older email processed after a newer one never replaces the newest price ──
def test_reverse_chronological_processing_keeps_newest_price(conn):
    lid = _add(conn, "<n3@x>", "1002", "2026-10-27T10:00:00+01:00", 450_000)   # newest, processed first
    _add(conn, "<n2@x>", "1002", "2026-10-24T10:00:00+02:00", 480_000)
    _add(conn, "<n1@x>", "1002", "2026-10-21T10:00:00+02:00", 500_000)         # oldest, processed last
    row = _listing(conn, lid)
    assert row["price"] == 450_000
    assert (row["published_at"], row["price_updated_at"]) == ("2026-10-21", "2026-10-27")
    assert _history(conn, lid) == [("2026-10-21", 500_000, "alert"), ("2026-10-24", 480_000, "alert"),
                                   ("2026-10-27", 450_000, "alert")]


# ── R11 tie rule: same day, different prices → the higher price and a conflict flag ──
@pytest.mark.parametrize("higher_first", [False, True], ids=["higher-then-lower", "lower-then-higher"])
def test_same_day_different_prices_keep_higher_and_flag(conn, higher_first):
    # 24 Oct: 510.000 at 09:00 and 500.000 at 18:00. The lower one is the later email, so "latest wins"
    # would give 500.000; the tie rule says the higher price, 510.000.
    steps = [("<c1@x>", "2026-10-24T09:00:00+02:00", 510_000), ("<c2@x>", "2026-10-24T18:00:00+02:00", 500_000)]
    for email_id, seen_at, price in (steps if higher_first else reversed(steps)):
        lid = _add(conn, email_id, "1003", seen_at, price)
    row = _listing(conn, lid)
    assert row["price"] == 510_000
    assert _flags(row) == ["precios en conflicto el 24/10/2026"]
    # data-model: one `alert` row per date where the price differs from the previous one
    assert _history(conn, lid) == [("2026-10-24", 510_000, "alert")]


# ── US2-4 / FR-035: price drop for a known listing (new-listing 670.000 on 23 Oct, drop 670.000 → 645.000 on 26 Oct) ──
@pytest.mark.parametrize("drop_first", [False, True], ids=["new-listing-first", "drop-first"])
def test_price_drop_for_known_listing_updates_it(conn, no_network, drop_first):
    lid = f"idealista:{DROP_CODE}"

    def known():
        _add(conn, "<k1@x>", DROP_CODE, "2026-10-23T10:00:00+02:00", 670_000)

    if drop_first:
        _fixture(conn, DROP_CODE)
        known()
    else:
        known()
        _fixture(conn, DROP_CODE)
    assert [r[0] for r in conn.execute("SELECT id FROM listings").fetchall()] == [lid]  # one listing, never two
    row = _listing(conn, lid)
    assert row["price"] == 645_000
    assert (row["published_at"], row["price_updated_at"]) == ("2026-10-23", "2026-10-26")
    assert _flags(row) == []  # stated previous price 670.000 equals the recorded one: no mismatch flag
    # 23 Oct 670.000 (alert); 26 Oct the stated previous price 670.000 (alert_previous, first), then 645.000
    assert _history(conn, lid) == [("2026-10-23", 670_000, "alert"), ("2026-10-26", 670_000, "alert_previous"),
                                   ("2026-10-26", 645_000, "alert")]


# ── FR-035: price drop for an unknown listing creates it ──
def test_price_drop_for_unknown_listing_creates_it(conn, no_network):
    out = _fixture(conn, DROP_CODE)
    lid = f"idealista:{DROP_CODE}"
    assert (out.listing_id, out.listing_change) == (lid, "new")
    row = _listing(conn, lid)
    assert row["price"] == 645_000
    assert row["published_at"] is None  # no new-listing alert seen
    assert row["price_updated_at"] == "2026-10-26"  # FR-035: a price-drop alert sets the updated date
    assert _flags(row) == []
    assert _history(conn, lid) == [("2026-10-26", 670_000, "alert_previous"), ("2026-10-26", 645_000, "alert")]
    assert conn.execute("SELECT previous_price FROM sightings WHERE listing_id=?", (lid,)).fetchone()[0] == 670_000


# ── FR-035: stated previous price ≠ recorded price → flag with both values ──
@pytest.mark.parametrize("drop_first", [False, True], ids=["in-order", "drop-processed-first"])
def test_previous_price_mismatch_flag(conn, drop_first):
    # recorded 700.000 on 20 Oct; the 26 Oct alert says it dropped from 670.000 to 645.000 (an alert was missed)
    steps = [lambda: _add(conn, "<m1@x>", "1004", "2026-10-20T10:00:00+02:00", 700_000),
             lambda: _add(conn, "<m2@x>", "1004", "2026-10-26T12:00:00+01:00", 645_000, previous=670_000)]
    for step in (reversed(steps) if drop_first else steps):
        step()
    row = _listing(conn, "idealista:1004")
    assert row["price"] == 645_000  # the new price is applied as usual
    assert _flags(row) == ["la alerta dice precio anterior 670.000 €, registrado 700.000 €"]
    assert _history(conn, "idealista:1004") == [
        ("2026-10-20", 700_000, "alert"), ("2026-10-26", 670_000, "alert_previous"), ("2026-10-26", 645_000, "alert")]


# ── FR-008 / spec edge case: a price drop older than the newest sighting goes to history only ──
@pytest.mark.parametrize("newest_first", [False, True], ids=["old-drop-first", "newest-first"])
def test_older_price_drop_than_newest_sighting_is_history_only(conn, newest_first):
    # newest: new-listing 28 Oct at 600.000. Older: drop 680.000 → 650.000 on 23 Oct.
    steps = [lambda: _add(conn, "<o1@x>", "1005", "2026-10-23T10:00:00+02:00", 650_000, previous=680_000),
             lambda: _add(conn, "<o2@x>", "1005", "2026-10-28T10:00:00+01:00", 600_000)]
    for step in (reversed(steps) if newest_first else steps):
        step()
    row = _listing(conn, "idealista:1005")
    assert row["price"] == 600_000  # the old drop (650.000) never replaces the newest price
    assert row["price_updated_at"] == "2026-10-28"  # the newest sighting's change, not the old drop's date
    assert row["published_at"] == "2026-10-28"  # the only new_listing sighting
    assert _flags(row) == []
    assert _history(conn, "idealista:1005") == [
        ("2026-10-23", 680_000, "alert_previous"), ("2026-10-23", 650_000, "alert"), ("2026-10-28", 600_000, "alert")]


# ── Article VIII: the same result whatever the order of processing ──
def _synthetic_ops():
    def op(email_id, code, seen_at, price, previous=None):
        return ("synthetic", email_id, code, seen_at, price, previous)

    return [
        op("<s1@x>", DROP_CODE, "2026-10-23T10:00:00+02:00", 670_000),            # known before the 26 Oct fixture drop
        op("<s2@x>", "9001", "2026-10-24T09:00:00+02:00", 510_000),               # same-day conflict, higher first
        op("<s3@x>", "9001", "2026-10-24T18:00:00+02:00", 500_000),
        op("<s4@x>", "9002", "2026-10-23T10:00:00+02:00", 650_000, 680_000),      # drop older than the newest sighting
        op("<s5@x>", "9002", "2026-10-28T10:00:00+01:00", 600_000),
        op("<s6@x>", "9003", "2026-10-20T10:00:00+02:00", 700_000),               # previous-price mismatch
        op("<s7@x>", "9003", "2026-10-26T12:00:00+01:00", 645_000, 670_000),
    ]


def _build(order):
    conn = db.connect(":memory:")
    ind_etl.seed_madrid_districts(conn)
    run_id = alerts.start_run(conn, "file_cli")
    for item in order:
        if isinstance(item, Path):
            alerts.process_message(conn, item.read_bytes(), origin="file", file_name=item.name, run_id=run_id)
        else:
            _, email_id, code, seen_at, price, previous = item
            lid = _sighting(conn, email_id, code, seen_at, "price_drop" if previous else "new_listing",
                            price=price, previous_price=previous, location_text="Getafe")
            derive.derive_listing(conn, lid)
    return conn


def _dump(conn):
    listings = [{k: r[k] for k in r.keys() if k != "first_run_id"}  # run ids are not derived from sightings
                for r in conn.execute("SELECT * FROM listings ORDER BY id").fetchall()]
    history = [tuple(r) for r in conn.execute(
        "SELECT listing_id, day, price, origin, email_id FROM price_history "
        "ORDER BY listing_id, day, origin='alert_previous' DESC, price, email_id").fetchall()]
    return listings, history


def test_order_independence_over_20_shuffles(no_network):
    items = [*sorted(EMAILS.glob("*.eml")), *_synthetic_ops()]
    rng = random.Random(22)
    reference = None
    for n in range(20):
        order = items[:]
        rng.shuffle(order)
        listings, history = _dump(_build(order))
        if reference is None:
            reference = (listings, history)
            by_id = {row["id"]: row for row in listings}
            # 11 imported fixtures (the 2021 email is rejected) + synthetic codes 9001, 9002, 9003
            assert len(listings) == 14
            drop = by_id[f"idealista:{DROP_CODE}"]  # synthetic 670.000 on 23 Oct, then the real drop on 26 Oct
            assert (drop["price"], drop["published_at"], drop["price_updated_at"]) == (645_000, "2026-10-23", "2026-10-26")
            assert by_id["idealista:9001"]["price"] == 510_000
            assert json.loads(by_id["idealista:9001"]["alert_flags"]) == ["precios en conflicto el 24/10/2026"]
            assert by_id["idealista:9002"]["price"] == 600_000
            assert json.loads(by_id["idealista:9003"]["alert_flags"]) == [
                "la alerta dice precio anterior 670.000 €, registrado 700.000 €"]
        assert (listings, history) == reference, f"shuffle {n} differs: {[getattr(i, 'name', i) for i in order]}"
