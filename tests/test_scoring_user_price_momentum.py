"""T041b - once a listing's price is user-owned, the alert price series no longer feeds momentum (FR-007, FR-036).

Rule under test (tasks.md T041b, review T040 round 1 finding 2): `field_sources.price` of `manual` or `csv`
(including a unit price set by PATCH on a development) means no alert changed the listing's price, so the alert
price series ("alert" and "alert_previous" history rows, derive.derive_listing) does not exist for it: momentum is
None, there is no "bajada de precio acumulada" flag, and the price-history route returns no alert-driven rows.

Alert series used (sightings, built by hand; Article VII):
  20 Oct 2026  new listing   800.000
  23 Oct 2026  price drop    800.000 -> 600.000   (the development "stated at 600.000")
History the old behaviour would keep: 800.000 (alert), 800.000 (alert_previous), 600.000 (alert) -> the ranking
reads first = 800.000 and last = 600.000:
  drop = 1 - 600.000 / 800.000 = 1 - 0.75 = 0.25 = 25 %
  momentum component = clamp(drop / 0.10) = clamp(2.5) = 1.0, flag "bajada de precio acumulada 25.0%".
(The 0.10 saturation is the existing scoring constant; the guard test below pins the 25 % case on a listing that
is not user-priced, so the number is calculated here, not read from the code under test.)

Price-history policy (FR-007: the price history records alert-driven changes "unless the current price was
entered by the user"; FR-036: the updated date is the date of the latest alert that changed the price; derive
rebuilds only origin alert/alert_previous rows): for a user-priced listing GET /price-history returns no row
whose origin is alert or alert_previous. Rows of other origins (null, user entries) are not asserted.
SCORING_VERSION stays 2.
"""
import json

import pytest
from fastapi.testclient import TestClient

from app import db, derive, scoring, zones
from app.main import create_app

from .conftest import EXAMPLE_NEEDS

DROP_FLAG = "bajada de precio acumulada"
ALERT_ORIGINS = {"alert", "alert_previous"}


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
    with TestClient(create_app(db_path, str(needs))) as c:
        yield c


@pytest.fixture
def seed(client, db_path):
    conn = db.connect(db_path)
    conn.isolation_level = None
    yield conn
    conn.close()


def _add(conn, email_id, code, seen_at, price, previous=None, development=0):
    alert_type = "price_drop" if previous else "new_listing"
    conn.execute("INSERT INTO alert_emails(email_id, origin, alert_date, alert_type, outcome) "
                 "VALUES(?, 'file', ?, ?, 'imported')", (email_id, seen_at, alert_type))
    lid = f"idealista:{code}"
    row = {"email_id": email_id, "listing_id": lid, "alert_type": alert_type, "seen_at": seen_at,
           "development": development, "price": price, "previous_price": previous, "location_text": "Getafe",
           "link_tracking": f"https://www.idealista.com/inmueble/{code}/?x=1",
           "link_direct": f"https://www.idealista.com/inmueble/{code}/"}
    conn.execute(f"INSERT INTO sightings({','.join(row)}) VALUES({','.join('?' * len(row))})", list(row.values()))
    derive.derive_listing(conn, lid)
    return lid


def _series(conn, code, development):
    _add(conn, f"<{code}a@x>", code, "2026-10-20T10:00:00+02:00", 800_000, development=development)
    return _add(conn, f"<{code}b@x>", code, "2026-10-23T10:00:00+02:00", 600_000, previous=800_000,
                development=development)


def _row(client, lid):
    return next(r for r in client.get("/api/listings").json() if r["id"] == lid)


def _sources(row):
    s = row["field_sources"]
    return json.loads(s) if isinstance(s, str) else (s or {})


def _no_drop_flag(row):
    return not any(DROP_FLAG in f for f in row["eval"]["flags"])


def _alert_rows(client, lid):
    resp = client.get(f"/api/listings/{lid}/price-history")
    assert resp.status_code == 200, resp.text
    return [r for r in resp.json() if r["origin"] in ALERT_ORIGINS]


def test_scoring_version_stays_2():
    assert scoring.SCORING_VERSION == 2


def test_development_unit_price_patch_drops_alert_momentum(seed, client, no_network):
    lid = _series(seed, "9001", development=1)
    assert _row(client, lid)["price"] == 600_000
    assert _row(client, lid)["eval"]["components"]["momentum"] is None  # unchosen development (R13)

    resp = client.patch(f"/api/listings/{lid}", json={"price": 450_000, "area_m2": 120, "bedrooms": 4})
    assert resp.status_code == 200, resp.text

    row = _row(client, lid)
    assert row["price"] == 450_000 and row["eval"]["price_drop"] is None
    assert row["eval"]["components"]["momentum"] is None  # old behaviour: 25 % -> 1.0 (module docstring)
    assert _no_drop_flag(row)


def test_price_history_route_has_no_alert_rows_for_user_price(seed, client, no_network):
    lid = _series(seed, "9001", development=1)
    assert len(_alert_rows(client, lid)) == 3  # 800.000 alert, 800.000 alert_previous, 600.000 alert

    assert client.patch(f"/api/listings/{lid}", json={"price": 450_000}).status_code == 200

    assert _alert_rows(client, lid) == []  # nothing for the UI to show as "antes del <fecha>"


def test_later_alert_price_change_keeps_user_price_and_no_momentum(seed, client, no_network):
    lid = _series(seed, "9001", development=1)
    assert client.patch(f"/api/listings/{lid}", json={"price": 450_000, "area_m2": 120, "bedrooms": 4}
                        ).status_code == 200
    before = _row(client, lid)

    # 30 Oct: an alert drops the stated price 600.000 -> 580.000, then the listing is re-derived from all sightings
    _add(seed, "<9001c@x>", "9001", "2026-10-30T10:00:00+01:00", 580_000, previous=600_000, development=1)
    assert client.patch(f"/api/listings/{lid}", json={"availability": "active"}).status_code == 200

    row = _row(client, lid)
    assert row["price"] == 450_000
    assert _sources(row)["price"] == "manual"
    assert row["price_updated_at"] == before["price_updated_at"]  # the alert did not change the user's price
    assert row["eval"]["components"]["momentum"] is None and row["eval"]["price_drop"] is None
    assert _no_drop_flag(row)
    assert _alert_rows(client, lid) == []


def test_user_price_on_an_ordinary_listing_also_drops_momentum(seed, client, no_network):
    lid = _series(seed, "9002", development=0)
    assert client.patch(f"/api/listings/{lid}", json={"price": 450_000}).status_code == 200

    row = _row(client, lid)
    assert row["eval"]["components"]["momentum"] is None and row["eval"]["price_drop"] is None
    assert _no_drop_flag(row)


def test_guard_alert_priced_listing_keeps_momentum(seed, client, no_network):
    lid = _series(seed, "9002", development=0)

    row = _row(client, lid)
    assert row["eval"]["price_drop"] == pytest.approx(0.25)  # 1 - 600000/800000, docstring
    assert row["eval"]["components"]["momentum"] == pytest.approx(1.0)
    assert any(DROP_FLAG in f and "25.0%" in f for f in row["eval"]["flags"])
    assert len(_alert_rows(client, lid)) == 3


def test_guard_patching_other_units_keeps_momentum(seed, client, no_network):
    lid = _series(seed, "9002", development=0)
    assert client.patch(f"/api/listings/{lid}", json={"area_m2": 120, "bedrooms": 4}).status_code == 200

    row = _row(client, lid)
    assert _sources(row).get("price") != "manual"
    assert row["price"] == 600_000
    assert row["eval"]["price_drop"] == pytest.approx(0.25)
    assert row["eval"]["components"]["momentum"] == pytest.approx(1.0)
    assert len(_alert_rows(client, lid)) == 3


# --- rank() on its own: stored alert rows must not feed a user-owned price ---------------------------------------
# Stored state the ranking can meet: field_sources says the price is the user's while price_history still holds
# alert / alert_previous rows (rows written before the price became the user's, or a path that did not re-derive).
# The ranking must not depend on derive having cleaned them up. Same hand-written series as the module docstring.

def _put_with_alert_series(conn, lid, price_source, price=450_000.0):
    conn.execute("INSERT OR IGNORE INTO zones(zone_id,name,municipality,level) VALUES('z','z','test','municipality')")
    conn.execute("INSERT INTO listings(id,source,url,property_type,price,area_m2,bedrooms,zone_id,development,"
                 "field_sources) VALUES(?,?,?,?,?,?,?,?,?,?)",
                 (lid, "alert", f"https://x.test/{lid}", "piso", price, 120.0, 4, "z", 0,
                  json.dumps({"price": price_source})))
    for day, p, origin in (("2026-10-20", 800_000, "alert"), ("2026-10-23", 800_000, "alert_previous"),
                           ("2026-10-23", 600_000, "alert")):
        conn.execute("INSERT INTO price_history(listing_id,day,price,origin) VALUES(?,?,?,?)", (lid, day, p, origin))
    conn.commit()


def _ev(conn, needs, lid):
    return next(r for r in scoring.rank(conn, needs) if r["id"] == lid)["eval"]


@pytest.mark.parametrize("source", ["manual", "csv"])
def test_rank_ignores_stored_alert_series_when_price_is_user_owned(conn, needs, source):
    _put_with_alert_series(conn, "L", source)

    ev = _ev(conn, needs, "L")

    assert ev["components"]["momentum"] is None  # old behaviour: 1 - 600000/800000 = 25 % -> 1.0
    assert ev["price_drop"] is None
    assert not any(DROP_FLAG in f for f in ev["flags"])


@pytest.mark.parametrize("source", ["alert", None])
def test_rank_guard_alert_owned_price_keeps_stored_series(conn, needs, source):
    _put_with_alert_series(conn, "L", source, price=600_000.0)

    ev = _ev(conn, needs, "L")

    assert ev["price_drop"] == pytest.approx(0.25)  # 1 - 600000/800000
    assert ev["components"]["momentum"] == pytest.approx(1.0)
    assert any(DROP_FLAG in f and "25.0%" in f for f in ev["flags"])
