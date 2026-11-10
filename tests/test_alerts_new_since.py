"""New since the last run (T047, US6, FR-021, data-model "listings.first_run_id", contracts/api.md "Listings").

Behaviour pinned here (decided by the coordinator, not by the code):
  1. `listings.first_run_id` is the import run in which the listing's first sighting was stored. It is set when
     the listing row is created from a sighting and NEVER changes afterwards (re-derivation, later runs,
     reprocess, merge keep it). A listing created by `reprocess` (an email that failed before and now imports)
     gets the reprocess run's id. Listings with no sighting (manual, CSV) keep NULL, and an alert that later
     arrives for such an existing listing does not set it.
  2. `GET /api/listings?new_since_last_run=true` returns only the listings whose first_run_id is NOT NULL and
     >= the id of the most recent run with kind != 'reprocess' AND status = 'ok'. So a reprocess made after the
     last import that creates a listing counts as new, a reprocess before it does not, and a failed or
     interrupted run is ignored when choosing "the last run". With no such run the result is []. Without the
     parameter (or with false) the endpoint is unchanged: every listing.
  3. Every listing in the response carries `first_run_id`.

Expected values are derived by hand from the anonymised fixtures (Article VI, VII): each file name ends with the
Idealista code of its single listing card, so the listing id is "idealista:<code>":
  2026-10-26 bajada de precio chalets ..._112842548   -> idealista:112842548  (DROP_NAME, 670.000 -> 645.000)
  2026-10-27 nuevo chalet pareado    ..._112923327   -> idealista:112923327  (NEW_NAME)
  2026-10-26 nuevo chalet independiente ..._112899473 -> idealista:112899473
  2026-10-27 nuevo piso apartamentos ..._112921923   -> idealista:112921923
  2026-10-28 nuevo chalet independiente ..._112477754 -> idealista:112477754
  2026-10-23 nuevo chalet independiente ..._112887282 -> idealista:112887282
The repeat sighting of 112842548 is `followup_drop` (reprocess_support): the same listing, a new Message-ID, one
more price drop on 2026-10-28. Run ids are never hard-coded: they are read from each run summary.
No network (no_network), everything stays in a temporary database.
"""
import base64
import sqlite3

import pytest
from fastapi.testclient import TestClient

from app import zones
from app.main import create_app

from .conftest import EXAMPLE_NEEDS
from .reprocess_support import DROP_LISTING, DROP_NAME, NEW_NAME, fixture, followup_drop, newer_reader, truncated

NEW_LISTING = "idealista:112923327"
INDEP_NAME = "2026-10-26_nuevo-chalet-independiente_chalets-en-tu-zona-personalizada_112899473.eml"
INDEP_LISTING = "idealista:112899473"
PISO_NAME = "2026-10-27_nuevo-piso_apartamentos-en-tu-zona-personalizada_112921923.eml"
PISO_LISTING = "idealista:112921923"
CHALET_NAME = "2026-10-28_nuevo-chalet-independiente_chalets-en-tu-zona-personalizada_112477754.eml"
CHALET_LISTING = "idealista:112477754"
OTHER_NAME = "2026-10-23_nuevo-chalet-independiente_viviendas-en-tu-zona-personalizada_112887282.eml"
OTHER_LISTING = "idealista:112887282"
BROKEN_ID = "<broken-1@example.invalid>"


@pytest.fixture(autouse=True)
def no_aliases(tmp_path, monkeypatch):
    monkeypatch.setattr(zones, "ALIASES_PATH", tmp_path / "zone_aliases.yaml")


@pytest.fixture
def client(tmp_path):
    needs = tmp_path / "needs.yaml"
    needs.write_text(EXAMPLE_NEEDS.read_text(encoding="utf-8"), encoding="utf-8")
    with TestClient(create_app(str(tmp_path / "t.db"), str(needs))) as c:
        yield c


def _import(client, raws):
    files = [{"name": f"m{i}.eml", "content_base64": base64.b64encode(raw).decode("ascii")}
             for i, raw in enumerate(raws)]
    resp = client.post("/api/alerts/import", json={"files": files})
    assert resp.status_code == 200, resp.text
    return resp.json()["run_id"]


def _reprocess(client, scope="failed"):
    resp = client.post("/api/alerts/reprocess", json={"scope": scope})
    assert resp.status_code == 200, resp.text
    return resp.json()["run_id"]


def _all(client):
    resp = client.get("/api/listings")
    assert resp.status_code == 200, resp.text
    return resp.json()


def _new(client, value="true"):
    resp = client.get("/api/listings", params={"new_since_last_run": value})
    assert resp.status_code == 200, resp.text
    return resp.json()


def _ids(listings):
    return sorted(x["id"] for x in listings)


def _first_run(client):
    """{listing id: first_run_id} as the API reports it (contract: every listing carries first_run_id)."""
    rows = _all(client)
    assert all("first_run_id" in x for x in rows)
    return {x["id"]: x["first_run_id"] for x in rows}


def _sql(tmp_path, sql, *args):
    c = sqlite3.connect(str(tmp_path / "t.db"))
    try:
        cur = c.execute(sql, args)
        c.commit()
        return cur.fetchall()
    finally:
        c.close()


# -- the main case: two batches, a repeat sighting across them -----------------------------------------
def test_new_since_last_run(client, no_network):
    # Batch A: three different listings, all new: 112842548, 112923327, 112899473.
    run_a = _import(client, [fixture(DROP_NAME), fixture(NEW_NAME), fixture(INDEP_NAME)])
    assert _ids(_new(client)) == sorted([DROP_LISTING, NEW_LISTING, INDEP_LISTING])  # all first seen in A, the last run
    # Batch B: three listings first seen now (112921923, 112477754, 112887282) and one repeat sighting of
    # 112842548 (followup_drop: same listing, other Message-ID, so it is stored and is NOT a new listing).
    run_b = _import(client, [followup_drop(fixture(DROP_NAME), "again-1"), fixture(PISO_NAME), fixture(CHALET_NAME),
                             fixture(OTHER_NAME)])
    assert run_b > run_a

    only_new = _new(client)
    assert _ids(only_new) == sorted([PISO_LISTING, CHALET_LISTING, OTHER_LISTING])  # exactly what B detected first
    assert DROP_LISTING not in _ids(only_new)  # seen in A and again in B: not new
    first = _first_run(client)
    assert first[DROP_LISTING] == run_a  # unchanged by the repeat sighting and by its re-derivation
    assert first[NEW_LISTING] == run_a and first[INDEP_LISTING] == run_a
    assert {first[x] for x in (PISO_LISTING, CHALET_LISTING, OTHER_LISTING)} == {run_b}
    assert all(x["first_run_id"] == run_b for x in only_new)
    assert _ids(_all(client)) == sorted([DROP_LISTING, NEW_LISTING, INDEP_LISTING, PISO_LISTING, CHALET_LISTING,
                                         OTHER_LISTING])  # without the parameter: everything


def test_param_absent_or_false_returns_all_listings(client, no_network):
    _import(client, [fixture(DROP_NAME), fixture(NEW_NAME)])
    _import(client, [fixture(PISO_NAME)])
    everything = sorted([DROP_LISTING, NEW_LISTING, PISO_LISTING])
    assert _ids(_all(client)) == everything
    assert _ids(_new(client, "false")) == everything
    assert _ids(_new(client, "true")) == [PISO_LISTING]  # and the filter really filters (A listings are older)


def test_first_run_id_is_in_every_listing_and_set_on_creation(client, no_network):
    run = _import(client, [fixture(DROP_NAME)])
    (listing,) = _all(client)
    assert listing["id"] == DROP_LISTING and listing["first_run_id"] == run


def test_no_runs_gives_empty_list(client, no_network):
    assert _new(client) == []  # no run at all
    assert _all(client) == []


def test_only_a_failed_run_gives_empty_list(client, tmp_path, no_network):
    _sql(tmp_path, "INSERT INTO import_runs(kind, started_at, status) VALUES('file_cli','2026-11-01T10:00:00','failed')")
    assert _new(client) == []


# -- which run is "the last run" ----------------------------------------------------------------------
def test_failed_run_is_skipped_when_choosing_the_last_run(client, tmp_path, no_network):
    run_a = _import(client, [fixture(DROP_NAME), fixture(NEW_NAME)])
    # a later run that failed (and one still running): neither is a "last run", so A still is
    _sql(tmp_path, "INSERT INTO import_runs(kind, started_at, status, error) VALUES('file_cli',"
                   "'2026-11-02T10:00:00','failed','OSError')")
    _sql(tmp_path, "INSERT INTO import_runs(kind, started_at, status) VALUES('sync','2026-11-03T10:00:00','running')")
    assert _ids(_new(client)) == sorted([DROP_LISTING, NEW_LISTING])
    assert _first_run(client) == {DROP_LISTING: run_a, NEW_LISTING: run_a}


# -- reprocess ------------------------------------------------------------------------------------------
def test_reprocess_keeps_first_run_id_of_existing_listings(client, monkeypatch, no_network):
    run_a = _import(client, [fixture(DROP_NAME), fixture(NEW_NAME)])
    newer_reader(monkeypatch)  # a newer reader version: scope "all" re-reads and re-derives every listing
    _reprocess(client, scope="all")
    assert _first_run(client) == {DROP_LISTING: run_a, NEW_LISTING: run_a}


def test_reprocess_created_listing_after_last_import_counts_as_new(client, monkeypatch, no_network):
    # Run 1 stores NEW_NAME (imported) and a truncated drop email (failed, no listing). The reprocess (run 2)
    # imports the drop: listing 112842548 is created by the reprocess run. The last non-reprocess ok run is 1,
    # 2 >= 1, so both listings are new since the last run: 112923327 (run 1) and 112842548 (run 2).
    full = fixture(DROP_NAME)
    run_1 = _import(client, [truncated(full, "broken-1"), fixture(NEW_NAME)])
    assert _first_run(client) == {NEW_LISTING: run_1}  # the failed email created nothing
    newer_reader(monkeypatch, understands={BROKEN_ID: full})
    run_2 = _reprocess(client)
    assert run_2 > run_1
    assert _first_run(client) == {NEW_LISTING: run_1, DROP_LISTING: run_2}  # the reprocess run's id
    assert _ids(_new(client)) == sorted([NEW_LISTING, DROP_LISTING])


def test_reprocess_before_a_later_import_is_not_new(client, monkeypatch, no_network):
    # Run 1 stores only the truncated drop; reprocess (run 2) creates 112842548; import (run 3) brings 112923327.
    # The last non-reprocess ok run is 3, so only 112923327 (first_run_id 3) is new; 112842548 keeps 2 (< 3).
    full = fixture(DROP_NAME)
    _import(client, [truncated(full, "broken-1")])
    newer_reader(monkeypatch, understands={BROKEN_ID: full})
    run_2 = _reprocess(client)
    run_3 = _import(client, [fixture(NEW_NAME)])
    assert run_3 > run_2
    assert _first_run(client) == {DROP_LISTING: run_2, NEW_LISTING: run_3}
    assert _ids(_new(client)) == [NEW_LISTING]


# -- listings without a sighting -----------------------------------------------------------------------
def test_manual_listing_is_never_new_and_a_later_alert_does_not_set_first_run_id(client, tmp_path, no_network):
    resp = client.post("/api/listings", json={"url": "https://x.test/1", "property_type": "chalet", "price": 450000,
                                              "area_m2": 180, "bedrooms": 4, "municipality": "Alcorcon"})
    assert resp.status_code == 200, resp.text
    manual_id = resp.json()["id"]
    # A listing that already holds the id an alert will later refer to (created by hand or by CSV before its alert
    # email arrives); inserted directly because the manual path does not know Idealista ids.
    _sql(tmp_path, "INSERT INTO listings(id, source, url, title, price, first_seen, last_seen) "
                   "VALUES(?, 'manual', 'https://x.test/2', 'manual', 400000, '2026-10-20', '2026-10-20')",
         INDEP_LISTING)
    run = _import(client, [fixture(INDEP_NAME), fixture(NEW_NAME)])  # INDEP_LISTING exists; NEW_LISTING is created
    first = _first_run(client)
    assert first[manual_id] is None and first[INDEP_LISTING] is None  # no sighting created them
    assert first[NEW_LISTING] == run
    assert _ids(_new(client)) == [NEW_LISTING]  # manual listings never appear under the filter
