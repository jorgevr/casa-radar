"""FU2 - merge keeps the combined price history (FR-018), rank() tolerates an empty `duplicates:` section
(research R15), and PUT /api/categories reports an unwritable rules file without leaking the local path.

Expected values are written by hand below (Article VII), never read back from the code under test.

1. After POST /api/listings/{src}/merge, GET /api/listings/{dst}/price-history returns the rows of BOTH listings,
   ordered by day, then `alert_previous` first, then insertion order (rowid; src rows were inserted before dst
   rows on the shared day, see the order of _add calls). Origins are kept as stored (alert, alert_previous, null).
   Today merge only sets merged_into, so the survivor still shows its own rows only.
2. needs["duplicates"] may be None, {} or hold null sub-values; research R15 defaults (3 % area, 5 % price,
   inclusive) then apply. `{**DEFAULTS, **{"area_pct_max": None}}` currently overrides a default with None.
3. (Merge double-submit guard: the second identical POST currently answers 200 and re-sets the same value, so
   data stays unchanged; no failing test is added. See handoff.)
4. PUT /api/categories on an unwritable rules path: JSON error, no full local path in the message, and the
   original file unchanged.
"""
import sqlite3

import pytest
import yaml
from fastapi.testclient import TestClient

from app import categories, db, derive, scoring, zones
from app.main import create_app

from .conftest import EXAMPLE_NEEDS


# -- shared helpers (same style as tests/test_price_history_route.py) ---------------------------------
@pytest.fixture(autouse=True)
def no_aliases(tmp_path, monkeypatch):
    monkeypatch.setattr(zones, "ALIASES_PATH", tmp_path / "zone_aliases.yaml")


@pytest.fixture
def db_path(tmp_path):
    return str(tmp_path / "t.db")


@pytest.fixture
def client(tmp_path, db_path):
    needs = tmp_path / "needs_api.yaml"
    needs.write_text(EXAMPLE_NEEDS.read_text(encoding="utf-8"), encoding="utf-8")
    with TestClient(create_app(db_path, str(needs))) as c:
        yield c


@pytest.fixture
def seed(client, db_path):
    conn = db.connect(db_path)
    conn.isolation_level = None
    yield conn
    conn.close()


def _add(conn, email_id, code, seen_at, price, previous=None):
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


def _history(client, lid):
    resp = client.get(f"/api/listings/{lid}/price-history")
    assert resp.status_code == 200, resp.text
    return [(r["day"], r["price"], r["origin"]) for r in resp.json()]


def _merge(client, src, dst):
    resp = client.post(f"/api/listings/{src}/merge", json={"into": dst})
    assert resp.status_code == 200, resp.text


# -- 1. combined price history on merge ---------------------------------------------------------------
def test_merge_combines_both_histories_on_the_survivor(seed, client, no_network):
    # src 2101: 20 Oct new at 720.000; 26 Oct drop 720.000 -> 650.000.
    #   rows: 20 Oct 720000 alert | 26 Oct 720000 alert_previous | 26 Oct 650000 alert
    # dst 2102: 23 Oct new at 700.000; 26 Oct drop 700.000 -> 660.000.
    #   rows: 23 Oct 700000 alert | 26 Oct 700000 alert_previous | 26 Oct 660000 alert
    # Insertion order: src 20 Oct, dst 23 Oct, src 26 Oct, dst 26 Oct, so on 26 Oct src rows precede dst rows.
    src = _add(seed, "<m1@x>", "2101", "2026-10-20T10:00:00+02:00", 720_000)
    dst = _add(seed, "<m2@x>", "2102", "2026-10-23T10:00:00+02:00", 700_000)
    _add(seed, "<m3@x>", "2101", "2026-10-26T10:00:00+01:00", 650_000, previous=720_000)
    _add(seed, "<m4@x>", "2102", "2026-10-26T12:00:00+01:00", 660_000, previous=700_000)
    assert _history(client, dst) == [("2026-10-23", 700_000, "alert"), ("2026-10-26", 700_000, "alert_previous"),
                                     ("2026-10-26", 660_000, "alert")]  # precondition: its own rows only

    _merge(client, src, dst)

    # day order; on 26 Oct both alert_previous rows come first (src, dst by rowid), then the alert rows.
    assert _history(client, dst) == [
        ("2026-10-20", 720_000, "alert"),
        ("2026-10-23", 700_000, "alert"),
        ("2026-10-26", 720_000, "alert_previous"),
        ("2026-10-26", 700_000, "alert_previous"),
        ("2026-10-26", 650_000, "alert"),
        ("2026-10-26", 660_000, "alert"),
    ]


def test_merge_keeps_legacy_null_origin_rows_of_the_merged_listing(seed, client, no_network):
    # src 2103 has a derived row (21 Oct 400000 alert) and a legacy row (origin null, 22 Oct 395000).
    # dst 2104: 23 Oct 410000 alert. Combined by day: 21 Oct, 22 Oct (origin None kept), 23 Oct.
    src = _add(seed, "<n1@x>", "2103", "2026-10-21T10:00:00+02:00", 400_000)
    dst = _add(seed, "<n2@x>", "2104", "2026-10-23T10:00:00+02:00", 410_000)
    seed.execute("INSERT INTO price_history(listing_id, day, price, origin) VALUES(?, '2026-10-22', 395000, NULL)",
                 (src,))

    _merge(client, src, dst)

    assert _history(client, dst) == [("2026-10-21", 400_000, "alert"), ("2026-10-22", 395_000, None),
                                     ("2026-10-23", 410_000, "alert")]


def test_chained_merge_gathers_every_history_on_the_final_survivor(seed, client, no_network):
    # a (2105) 20 Oct 500000 -> merged into b (2106) 21 Oct 510000 -> merged into c (2107) 22 Oct 520000.
    a = _add(seed, "<o1@x>", "2105", "2026-10-20T10:00:00+02:00", 500_000)
    b = _add(seed, "<o2@x>", "2106", "2026-10-21T10:00:00+02:00", 510_000)
    c = _add(seed, "<o3@x>", "2107", "2026-10-22T10:00:00+02:00", 520_000)

    _merge(client, a, b)
    _merge(client, b, c)

    assert _history(client, c) == [("2026-10-20", 500_000, "alert"), ("2026-10-21", 510_000, "alert"),
                                   ("2026-10-22", 520_000, "alert")]


def test_merge_does_not_lose_stored_rows(seed, db_path, client, no_network):
    # Article IX: nothing is deleted; every price_history row present before the merge is still stored after it.
    src = _add(seed, "<p1@x>", "2108", "2026-10-21T10:00:00+02:00", 400_000)
    dst = _add(seed, "<p2@x>", "2109", "2026-10-22T10:00:00+02:00", 410_000)
    c = sqlite3.connect(db_path)
    before = c.execute("SELECT COUNT(*) FROM price_history").fetchone()[0]
    c.close()

    _merge(client, src, dst)

    c = sqlite3.connect(db_path)
    after = c.execute("SELECT COUNT(*) FROM price_history").fetchone()[0]
    c.close()
    assert before == 2 and after >= before
    assert len(_history(client, dst)) == 2


# -- 2. rank() with an empty / null `duplicates` section ----------------------------------------------
def _put(conn, lid, area=100.0, price=400_000.0):
    conn.execute("INSERT OR IGNORE INTO zones(zone_id,name,municipality,level) "
                 "VALUES('zona-a','zona-a','test','municipality')")
    conn.execute(
        "INSERT INTO listings(id,source,url,property_type,price,area_m2,bedrooms,zone_id,development)"
        " VALUES(?,?,?,?,?,?,?,?,0)", (lid, "alert", f"https://x.test/{lid}", "piso", price, area, 3, "zona-a"))
    conn.commit()


def _dup_flags(conn, needs, lid):
    rows = {r["id"]: r for r in scoring.rank(conn, needs)}
    return [f for f in rows[lid]["eval"]["flags"] if "duplicado" in f]


@pytest.mark.parametrize("section", [None, {}, {"area_pct_max": None}, {"price_pct_max": None},
                                     {"area_pct_max": None, "price_pct_max": None}])
def test_rank_with_empty_or_null_duplicates_applies_defaults(conn, needs, section):
    # Defaults (R15): area 3 %, price 5 %, inclusive. A=100 m2/400000, B=97 m2/380000:
    # area 3/100 = 0.03 <= 0.03 and price 20000/400000 = 0.05 <= 0.05 -> flagged on both sides.
    needs = {**needs, "duplicates": section}
    _put(conn, "A")
    _put(conn, "B", area=97.0, price=380_000.0)

    assert _dup_flags(conn, needs, "A") == ["posible duplicado de B"]
    assert _dup_flags(conn, needs, "B") == ["posible duplicado de A"]


def test_rank_null_sub_value_falls_back_to_default_not_to_unlimited(conn, needs):
    # area_pct_max null -> default 0.03; A=100 vs B=96.99 differ by 3.01/100 = 0.0301 > 0.03 -> not flagged.
    needs = {**needs, "duplicates": {"area_pct_max": None}}
    _put(conn, "A")
    _put(conn, "B", area=96.99)

    assert _dup_flags(conn, needs, "A") == []


def test_rank_null_sub_value_keeps_the_other_configured_value(conn, needs):
    # price_pct_max null -> default 0.05, area_pct_max 0.10 configured: A=100 vs B=92 -> 8/100 = 0.08 <= 0.10,
    # price equal -> flagged. With the 0.03 area default it would not be, so the configured value is honoured.
    needs = {**needs, "duplicates": {"area_pct_max": 0.10, "price_pct_max": None}}
    _put(conn, "A")
    _put(conn, "B", area=92.0)

    assert _dup_flags(conn, needs, "A") == ["posible duplicado de B"]


# -- 4. PUT /api/categories with an unwritable rules file ---------------------------------------------
def test_put_categories_unwritable_path_is_a_json_error_without_the_local_path(tmp_path, monkeypatch, client,
                                                                               no_network):
    # The rules path is a directory: replacing it fails with an OSError. The tracked file is not used.
    rules_dir = tmp_path / "secret-folder-name" / "alert_categories.yaml"
    rules_dir.mkdir(parents=True)
    monkeypatch.setattr(categories, "CATEGORIES_PATH", rules_dir)

    resp = client.put("/api/categories", json={"rules": [{"contains": "obra nueva", "category": "obra nueva"}]})

    assert resp.status_code in (500, 400, 403, 409, 507), resp.text
    assert resp.headers["content-type"].startswith("application/json")
    body = resp.json()
    message = str(body.get("detail") or body.get("message") or body.get("error") or "")
    assert message, body
    assert str(rules_dir) not in resp.text and str(tmp_path) not in resp.text
    assert "secret-folder-name" not in resp.text  # directory names of the local path are not leaked either
    assert rules_dir.is_dir() and list(rules_dir.iterdir()) == []  # nothing written


def test_put_categories_write_failure_leaves_the_original_file_unchanged(tmp_path, monkeypatch, client, no_network):
    original = [{"contains": "viviendas", "category": "venta"}]
    path = tmp_path / "private-dir" / "alert_categories.yaml"
    path.parent.mkdir()
    path.write_text(yaml.safe_dump(original), encoding="utf-8")
    before = path.read_bytes()
    monkeypatch.setattr(categories, "CATEGORIES_PATH", path)

    def boom(rules):
        raise PermissionError(13, "Permission denied", str(path))

    monkeypatch.setattr(categories, "save_rules", boom)

    resp = client.put("/api/categories", json={"rules": [{"contains": "chalets", "category": "chalet"}]})

    assert resp.status_code >= 400, resp.text
    assert resp.headers["content-type"].startswith("application/json")
    assert str(path) not in resp.text and "private-dir" not in resp.text
    assert path.read_bytes() == before
