"""PATCH /api/listings/{id} accepts unit values price, area_m2, bedrooms (T041, US5, FR-023/FR-034).

Contract (contracts/api.md): the three values are recorded in `field_sources` as `manual`, stored on the
listing and protected from later alert re-derivation (data-model, FR-023). Expected values below are
chosen by hand (the user's numbers), never read back from the code's output. `/api/export.csv` already
carries `scoring_version` since T029 (tests/test_api_sorting.py); the last test here is only a guard.
"""
import base64
import csv
import io
import json

import pytest
from fastapi.testclient import TestClient

from app import zones
from app.main import create_app

from .conftest import EMAILS, EXAMPLE_NEEDS

DROP_TORREJON = "2026-10-26_bajada-de-precio_chalets-en-tu-zona-personalizada_112842548.eml"
NEW_CHALET = "2026-10-23_nuevo-chalet-independiente_viviendas-en-tu-zona-personalizada_112887282.eml"
UNITS = [("price", 417000), ("area_m2", 131.5), ("bedrooms", 4)]  # hand-picked, unlike any alert value


@pytest.fixture(autouse=True)
def no_aliases(tmp_path, monkeypatch):
    monkeypatch.setattr(zones, "ALIASES_PATH", tmp_path / "zone_aliases.yaml")


@pytest.fixture
def client(tmp_path):
    needs = tmp_path / "needs.yaml"
    needs.write_text(EXAMPLE_NEEDS.read_text(encoding="utf-8"), encoding="utf-8")
    with TestClient(create_app(str(tmp_path / "t.db"), str(needs))) as c:
        yield c


@pytest.fixture
def lid(client):
    body = {"files": [{"name": n, "content_base64": base64.b64encode((EMAILS / n).read_bytes()).decode("ascii")}
                      for n in (DROP_TORREJON, NEW_CHALET)]}
    assert client.post("/api/alerts/import", json=body).status_code == 200
    rows = client.get("/api/listings").json()
    return next(r["id"] for r in rows if "112842548" in r["id"])


def _get(client, lid):
    return next(r for r in client.get("/api/listings").json() if r["id"] == lid)


def _sources(row):
    s = row["field_sources"]
    return json.loads(s) if isinstance(s, str) else (s or {})


@pytest.mark.parametrize("field, value", UNITS)
def test_patch_unit_value_is_stored_and_marked_manual(client, lid, no_network, field, value):
    resp = client.patch(f"/api/listings/{lid}", json={field: value})

    assert resp.status_code == 200, resp.text
    row = _get(client, lid)
    assert row[field] == value
    assert _sources(row)[field] == "manual"


def test_patch_all_three_together(client, lid, no_network):
    resp = client.patch(f"/api/listings/{lid}", json=dict(UNITS))

    assert resp.status_code == 200, resp.text
    row = _get(client, lid)
    for field, value in UNITS:
        assert row[field] == value
        assert _sources(row)[field] == "manual"


@pytest.mark.parametrize("field, value", UNITS)
def test_manual_unit_survives_later_alert_derivation(client, lid, no_network, field, value):
    client.patch(f"/api/listings/{lid}", json={field: value})
    # a PATCH of availability re-derives the listing from its stored alert sightings
    assert client.patch(f"/api/listings/{lid}", json={"availability": "gone"}).status_code == 200
    assert client.patch(f"/api/listings/{lid}", json={"availability": "active"}).status_code == 200

    row = _get(client, lid)
    assert row[field] == value
    assert _sources(row)[field] == "manual"


BAD = [
    ("price", -1), ("price", 0), ("price", "abc"), ("price", True), ("price", False),
    ("area_m2", -50), ("area_m2", 0), ("area_m2", "abc"), ("area_m2", True),
    ("bedrooms", -1), ("bedrooms", "abc"), ("bedrooms", True), ("bedrooms", False), ("bedrooms", 2.5),
]


@pytest.mark.parametrize("field, value", BAD)
def test_invalid_unit_value_is_400_and_changes_nothing(client, lid, no_network, field, value):
    before = _get(client, lid)

    resp = client.patch(f"/api/listings/{lid}", json={field: value})

    assert resp.status_code == 400, resp.text
    assert _get(client, lid) == before


def test_invalid_value_alongside_a_valid_one_changes_nothing(client, lid, no_network):
    before = _get(client, lid)

    resp = client.patch(f"/api/listings/{lid}", json={"price": 417000, "area_m2": -5})

    assert resp.status_code == 400, resp.text
    assert _get(client, lid) == before


def test_export_csv_still_has_scoring_version_guard(client, lid, no_network):
    # Guard only: the column exists since T029 and is asserted in tests/test_api_sorting.py.
    resp = client.get("/api/export.csv")

    assert resp.status_code == 200
    header = next(csv.reader(io.StringIO(resp.text)))
    assert "scoring_version" in header


# ── overflow and atomicity (review T040 finding 1) ────────────────────────────────────────────────
# Assumed bounds: integers must fit SQLite's signed 64-bit range (|n| < 2**63); price and area_m2 must
# also be below 1e12 (a sane cap far above any home price or area); 1e308 and inf-like values are 400.
@pytest.fixture
def soft_client(tmp_path):
    """Like `client`, but a server error comes back as a 500 response instead of raising in the test."""
    needs = tmp_path / "needs2.yaml"
    needs.write_text(EXAMPLE_NEEDS.read_text(encoding="utf-8"), encoding="utf-8")
    with TestClient(create_app(str(tmp_path / "t2.db"), str(needs)), raise_server_exceptions=False) as c:
        yield c


@pytest.fixture
def slid(soft_client):
    body = {"files": [{"name": n, "content_base64": base64.b64encode((EMAILS / n).read_bytes()).decode("ascii")}
                      for n in (DROP_TORREJON, NEW_CHALET)]}
    assert soft_client.post("/api/alerts/import", json=body).status_code == 200
    return next(r["id"] for r in soft_client.get("/api/listings").json() if "112842548" in r["id"])


OUT_OF_RANGE = [
    ("price", 2**63), ("price", -(2**63) - 1), ("price", 10**30),
    ("area_m2", 2**63), ("area_m2", 10**30),
    ("bedrooms", 2**63), ("bedrooms", 10**30), ("bedrooms", -(2**63) - 1),
    ("price", 1e308), ("price", 1e12), ("area_m2", 1e308), ("area_m2", 1e12),
]


@pytest.mark.parametrize("field, value", OUT_OF_RANGE)
def test_out_of_range_unit_is_400_not_500_and_changes_nothing(soft_client, slid, no_network, field, value):
    before = _get(soft_client, slid)

    resp = soft_client.patch(f"/api/listings/{slid}", json={field: value})

    assert resp.status_code == 400, resp.text
    assert _get(soft_client, slid) == before


@pytest.mark.parametrize("bad", [{"price": 10**30}, {"area_m2": 1e308}, {"bedrooms": 2**63}, {"price": -1}])
def test_notes_and_status_are_not_written_when_a_unit_value_is_invalid(soft_client, slid, no_network, bad):
    before = _get(soft_client, slid)

    resp = soft_client.patch(f"/api/listings/{slid}", json={"notes": "X", "status": "shortlist", **bad})

    assert resp.status_code == 400, resp.text
    assert _get(soft_client, slid) == before
    # a later, unrelated request that commits must not save anything left over from the failed one
    assert soft_client.patch(f"/api/listings/{slid}", json={"availability": "gone"}).status_code == 200
    after = _get(soft_client, slid)
    assert after["notes"] == before["notes"]
    assert after["status"] == before["status"]
    for field in ("price", "area_m2", "bedrooms"):
        assert after[field] == before[field]
