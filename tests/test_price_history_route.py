"""GET /api/listings/{id}/price-history (T029b; tasks.md T030, data-model § Extended: price_history, research R11).

Contract under test: 200 and a JSON list of {day, price, origin}; day is an ISO date, origin is `alert`,
`alert_previous` or null (legacy / API rows); ordered by day, then `alert_previous` before the others on the
same day, then insertion order (rowid). email_id is internal and not exposed. Unknown id -> 404. A merged
listing still answers for its own id (data is never deleted, Article IX). GET has no side effects.

Data is built through sightings and derive.derive_listing; expected rows are written by hand below
(Article VII), never read back from the code under test.

Distinguishing "unknown id" from "route missing": FastAPI answers 404 for a missing route too, so the 404 test
first asks the SAME client for a real listing and requires 200; only then is the unknown id's 404 meaningful.
"""
import sqlite3

import pytest
from fastapi.testclient import TestClient

from app import db, derive, zones
from app.main import create_app

from .conftest import EXAMPLE_NEEDS


@pytest.fixture(autouse=True)
def no_aliases(tmp_path, monkeypatch):
    monkeypatch.setattr(zones, "ALIASES_PATH", tmp_path / "zone_aliases.yaml")


@pytest.fixture
def db_path(tmp_path):
    return str(tmp_path / "t.db")


@pytest.fixture
def client(tmp_path, db_path):
    needs = tmp_path / "needs.yaml"
    needs.write_text(EXAMPLE_NEEDS.read_text(encoding="utf-8"), encoding="utf-8")
    # context manager first, `no_network` after (see tests/test_api_alerts.py)
    with TestClient(create_app(db_path, str(needs))) as c:
        yield c


@pytest.fixture
def seed(client, db_path):
    """A second connection on the app's database file, in autocommit, for building the data the route reads."""
    conn = db.connect(db_path)
    conn.isolation_level = None
    yield conn
    conn.close()

def _add(conn, email_id, code, seen_at, price, previous=None):
    """Record one sighting (price_drop when `previous` is given) and re-derive the listing."""
    alert_type = "price_drop" if previous else "new_listing"
    conn.execute("INSERT INTO alert_emails(email_id, origin, alert_date, alert_type, outcome) "
                 "VALUES(?, 'file', ?, ?, 'imported')", (email_id, seen_at, alert_type))
    lid = f"idealista:{code}"
    row = {"email_id": email_id, "listing_id": lid, "alert_type": alert_type, "seen_at": seen_at,
           "development": 0, "price": price, "previous_price": previous, "location_text": "Getafe",
           "link_tracking": f"https://www.idealista.com/inmueble/{code}/?x=1",
           "link_direct": f"https://www.idealista.com/inmueble/{code}/"}
    conn.execute(f"INSERT INTO sightings({','.join(row)}) VALUES({','.join('?' * len(row))})", list(row.values()))
    derive.derive_listing(conn, lid)
    return lid


def _url(lid):
    return f"/api/listings/{lid}/price-history"


def _tuples(body):
    return [(r["day"], r["price"], r["origin"]) for r in body]


def test_price_drop_history_in_order(seed, client, no_network):
    # 23 Oct: new listing at 670.000. 26 Oct: drop alert "de 670.000 a 645.000".
    # Hand-written rows: 23 Oct 670.000 alert; on 26 Oct the stated previous price 670.000 (alert_previous,
    # first on its day) and then the new price 645.000 (alert).
    lid = _add(seed, "<a1@x>", "2001", "2026-10-23T10:00:00+02:00", 670_000)
    _add(seed, "<a2@x>", "2001", "2026-10-26T12:00:00+01:00", 645_000, previous=670_000)

    resp = client.get(_url(lid))

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert isinstance(body, list)
    assert _tuples(body) == [("2026-10-23", 670_000, "alert"), ("2026-10-26", 670_000, "alert_previous"),
                             ("2026-10-26", 645_000, "alert")]
    assert all(set(r) == {"day", "price", "origin"} for r in body)  # email_id is not exposed


def test_same_day_alert_previous_sorts_before_alert_for_a_drop_only_listing(seed, client, no_network):
    # Only the drop alert was ever seen (26 Oct, 670.000 -> 645.000): both rows share the day; the
    # alert_previous (670.000) comes first, then the alert row (645.000).
    lid = _add(seed, "<b1@x>", "2002", "2026-10-26T12:00:00+01:00", 645_000, previous=670_000)

    resp = client.get(_url(lid))

    assert resp.status_code == 200, resp.text
    assert _tuples(resp.json()) == [("2026-10-26", 670_000, "alert_previous"), ("2026-10-26", 645_000, "alert")]


def test_legacy_rows_with_null_origin_are_included_and_ordered(seed, client, no_network):
    # Derived: 20 Oct 500.000 alert; 26 Oct a drop 500.000 -> 480.000 (alert_previous 500.000, alert 480.000).
    # Legacy rows (origin null, e.g. from the API) are inserted afterwards, so they have the highest rowids:
    #   24 Oct 490.000 sorts by day between the two derived days;
    #   26 Oct 485.000 shares the day with the alert pair: alert_previous first, then rowid order
    #   (alert, then the later-inserted legacy row).
    lid = _add(seed, "<c1@x>", "2003", "2026-10-20T10:00:00+02:00", 500_000)
    _add(seed, "<c2@x>", "2003", "2026-10-26T10:00:00+01:00", 480_000, previous=500_000)
    seed.execute("INSERT INTO price_history(listing_id, day, price, origin) VALUES(?, '2026-10-26', 485000, NULL)",
                 (lid,))
    seed.execute("INSERT INTO price_history(listing_id, day, price, origin) VALUES(?, '2026-10-24', 490000, NULL)",
                 (lid,))

    resp = client.get(_url(lid))

    assert resp.status_code == 200, resp.text
    assert _tuples(resp.json()) == [("2026-10-20", 500_000, "alert"), ("2026-10-24", 490_000, None),
                                    ("2026-10-26", 500_000, "alert_previous"), ("2026-10-26", 480_000, "alert"),
                                    ("2026-10-26", 485_000, None)]


def test_listing_without_history_returns_empty_list(seed, client, no_network):
    lid = _add(seed, "<d1@x>", "2004", "2026-10-23T10:00:00+02:00", 300_000)
    seed.execute("DELETE FROM price_history WHERE listing_id=?", (lid,))

    resp = client.get(_url(lid))

    assert resp.status_code == 200, resp.text
    assert resp.json() == []


def test_unknown_listing_is_404_while_a_real_one_is_200(seed, client, no_network):
    # A missing route also answers 404, so the real listing must answer 200 on the same client first.
    lid = _add(seed, "<e1@x>", "2005", "2026-10-23T10:00:00+02:00", 300_000)

    assert client.get(_url(lid)).status_code == 200
    assert client.get(_url("idealista:999999")).status_code == 404


def test_merged_listing_still_answers_for_its_own_id(seed, client, no_network):
    # Article IX: merging hides a listing, it never deletes its data. 2006 (400.000 on 21 Oct) is merged into 2007.
    src = _add(seed, "<f1@x>", "2006", "2026-10-21T10:00:00+02:00", 400_000)
    dst = _add(seed, "<f2@x>", "2007", "2026-10-22T10:00:00+02:00", 410_000)
    seed.execute("UPDATE listings SET merged_into=? WHERE id=?", (dst, src))

    resp = client.get(_url(src))

    assert resp.status_code == 200, resp.text
    assert _tuples(resp.json()) == [("2026-10-21", 400_000, "alert")]
    resp = client.get(_url(dst))
    assert resp.status_code == 200, resp.text
    assert _tuples(resp.json()) == [("2026-10-22", 410_000, "alert")]  # the target's own history, not combined


def test_get_has_no_write_side_effects(seed, db_path, client, no_network):
    lid = _add(seed, "<g1@x>", "2008", "2026-10-23T10:00:00+02:00", 670_000)
    _add(seed, "<g2@x>", "2008", "2026-10-26T12:00:00+01:00", 645_000, previous=670_000)

    def dump():
        c = sqlite3.connect(db_path)
        try:
            return {t: c.execute(f"SELECT * FROM {t} ORDER BY rowid").fetchall()
                    for t in ("price_history", "listings", "sightings", "alert_emails")}
        finally:
            c.close()

    before = dump()
    first = client.get(_url(lid))
    second = client.get(_url(lid))

    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    assert first.json() == second.json() != []
    assert dump() == before
