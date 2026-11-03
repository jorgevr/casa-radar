"""HTTP side of alert categories (T031 part 2; implemented by T035): GET/PUT /api/categories and
PATCH /api/listings/{id} with new_build true|false|null.

Contract (contracts/api.md "Categories", FR-031, FR-033, data-model):
  GET /api/categories -> {"rules": [{contains, category}, ...],
                          "search_names": [{"name", "category", "emails"}, ...]}  (emails = stored emails with that name)
  PUT /api/categories {"rules": [...]} saves the rules and re-derives every stored email, sighting and listing
      without re-importing; an invalid body is a 400 and saves nothing.
  PATCH new_build true|false -> new_build 1|0 with new_build_origin 'user'; null clears the user value.

Assumptions (see handoff): the rules file path is app.categories.CATEGORIES_PATH, monkeypatched into tmp_path;
the tracked config/alert_categories.yaml is only COPIED as the starting rules and never touched. GET
/api/listings returns `categories` as a list. null: new_build and new_build_origin become NULL, then the usual
derivation applies (so an email that states new-build gives back 1 / 'email').

Data comes from the anonymised fixtures through POST /api/alerts/import; expected values are written by hand
from the fixture file names (search name = text after "en tu búsqueda:" in the subject).
"""
import base64
import importlib
import json
import sqlite3

import pytest
import yaml
from fastapi.testclient import TestClient

from app import zones
from app.main import create_app

from .conftest import EMAILS, EXAMPLE_NEEDS, ROOT

TRACKED_RULES = ROOT / "config" / "alert_categories.yaml"

# name of the search -> fixture files (all importable: see tests/test_api_alerts.py for the first and second)
OBRA = ["2026-10-22_nueva-obra-nueva_obra-nueva-en-tu-zona-personalizada_112882173.eml"]
VIVIENDAS = ["2026-10-23_bajada-de-precio_viviendas-en-tu-zona-personalizada_112658090.eml",
             "2026-10-23_bajada-de-precio_viviendas-en-tu-zona-personalizada_112692121.eml"]
CHALETS = ["2026-10-26_bajada-de-precio_chalets-en-tu-zona-personalizada_112842548.eml",
           "2026-10-26_nuevo-chalet-independiente_chalets-en-tu-zona-personalizada_112899473.eml"]
APARTAMENTOS = ["2026-10-27_nuevo-piso_apartamentos-en-tu-zona-personalizada_112921923.eml"]
NAMES = {"Obra nueva en tu zona personalizada": OBRA, "Viviendas en tu zona personalizada": VIVIENDAS,
         "chalets en tu zona personalizada": CHALETS, "apartamentos en tu zona personalizada": APARTAMENTOS}

START_RULES = [{"contains": "obra nueva en tu zona personalizada", "category": "new-build"},
               {"contains": "chalets en tu zona personalizada", "category": "house"},
               {"contains": "apartamentos en tu zona personalizada", "category": "flat"}]  # = tracked file


@pytest.fixture(autouse=True)
def no_aliases(tmp_path, monkeypatch):
    monkeypatch.setattr(zones, "ALIASES_PATH", tmp_path / "zone_aliases.yaml")


@pytest.fixture
def rules_path(tmp_path, monkeypatch):
    """The rules file for the app under test: a copy of the tracked one, in tmp_path."""
    mod = importlib.import_module("app.categories")  # missing until T033
    path = tmp_path / "alert_categories.yaml"
    path.write_text(TRACKED_RULES.read_text(encoding="utf-8"), encoding="utf-8")
    monkeypatch.setattr(mod, "CATEGORIES_PATH", path)
    return path


@pytest.fixture
def db_path(tmp_path):
    return str(tmp_path / "t.db")


@pytest.fixture
def client(tmp_path, db_path, rules_path):
    needs = tmp_path / "needs.yaml"
    needs.write_text(EXAMPLE_NEEDS.read_text(encoding="utf-8"), encoding="utf-8")
    # context manager first, `no_network` after (see tests/test_api_alerts.py)
    with TestClient(create_app(db_path, str(needs))) as c:
        yield c


@pytest.fixture
def imported(client, no_network):
    files = [n for names in NAMES.values() for n in names]
    resp = client.post("/api/alerts/import", json={"files": [
        {"name": n, "content_base64": base64.b64encode((EMAILS / n).read_bytes()).decode("ascii")} for n in files]})
    assert resp.status_code == 200, resp.text
    assert resp.json()["n_imported"] == len(files)  # setup sanity: all of them stored
    return client


def _db(db_path):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def _listings(client):
    resp = client.get("/api/listings")
    assert resp.status_code == 200, resp.text
    return resp.json()["listings"] if isinstance(resp.json(), dict) else resp.json()


def _listing_ids(db_path, search_name):
    with _db(db_path) as c:
        return sorted({r[0] for r in c.execute(
            "SELECT s.listing_id FROM sightings s JOIN alert_emails e ON e.email_id=s.email_id "
            "WHERE e.search_name=?", (search_name,))})


def _by_name(body):
    return {x["name"]: x for x in body["search_names"]}


def _put(client, rules):
    return client.put("/api/categories", json={"rules": rules})


# ── GET ──────────────────────────────────────────────────────────────────────────────────────────────
def test_get_returns_rules_and_search_names_with_counts(imported):
    resp = imported.get("/api/categories")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["rules"] == START_RULES
    by_name = _by_name(body)
    assert set(by_name) == set(NAMES)
    # hand count: files per search name above; categories from START_RULES (no rule for "Viviendas...")
    assert {n: (x["category"], x["emails"]) for n, x in by_name.items()} == {
        "Obra nueva en tu zona personalizada": ("new-build", 1),
        "Viviendas en tu zona personalizada": ("unknown", 2),
        "chalets en tu zona personalizada": ("house", 2),
        "apartamentos en tu zona personalizada": ("flat", 1)}


# ── PUT ──────────────────────────────────────────────────────────────────────────────────────────────
NEW_RULES = [{"contains": "VIVIENDAS en tu ZONA", "category": "flat"},          # case-insensitive match
             {"contains": "obra nueva", "category": "new-build"}]


def test_put_saves_rules_and_get_returns_them(imported, rules_path):
    resp = _put(imported, NEW_RULES)
    assert resp.status_code == 200, resp.text
    assert imported.get("/api/categories").json()["rules"] == NEW_RULES
    assert yaml.safe_load(rules_path.read_text(encoding="utf-8")) == NEW_RULES  # saved in the file, as a list


def test_put_rederives_stored_emails_without_reimport(imported, db_path):
    assert _put(imported, NEW_RULES).status_code == 200
    by_name = _by_name(imported.get("/api/categories").json())
    # new rules: Viviendas -> flat, Obra nueva -> new-build; chalets and apartamentos now match nothing
    assert {n: x["category"] for n, x in by_name.items()} == {
        "Obra nueva en tu zona personalizada": "new-build", "Viviendas en tu zona personalizada": "flat",
        "chalets en tu zona personalizada": "unknown", "apartamentos en tu zona personalizada": "unknown"}
    with _db(db_path) as c:
        assert {r["category"] for r in c.execute(
            "SELECT category FROM alert_emails WHERE search_name='Viviendas en tu zona personalizada'")} == {"flat"}
        assert {r["category"] for r in c.execute(
            "SELECT s.category FROM sightings s JOIN alert_emails e ON e.email_id=s.email_id "
            "WHERE e.search_name='chalets en tu zona personalizada'")} == {"unknown"}


def test_put_changes_listing_categories_and_flag_in_get_listings(imported, db_path):
    ids = _listing_ids(db_path, "Viviendas en tu zona personalizada")
    assert ids, "setup: the Viviendas alerts produced listings"
    before = {x["id"]: x for x in _listings(imported) if x["id"] in ids}
    assert all("encontrado vía: búsqueda desconocida" in x["eval"]["flags"] for x in before.values())

    assert _put(imported, NEW_RULES).status_code == 200
    after = {x["id"]: x for x in _listings(imported) if x["id"] in ids}
    assert set(after) == set(ids)
    for x in after.values():
        assert "flat" in x["categories"]
        assert "unknown" not in x["categories"]
        assert "encontrado vía: búsqueda desconocida" not in x["eval"]["flags"]
        assert any(f.startswith("encontrado vía: ") and "flat" in f for f in x["eval"]["flags"])


def test_put_with_conflicting_rules_gives_unknown(imported):
    rules = [{"contains": "viviendas", "category": "flat"}, {"contains": "zona personalizada", "category": "house"}]
    assert _put(imported, rules).status_code == 200
    by_name = _by_name(imported.get("/api/categories").json())
    assert by_name["Viviendas en tu zona personalizada"]["category"] == "unknown"   # flat vs house
    assert by_name["chalets en tu zona personalizada"]["category"] == "house"      # only the second matches


def test_put_empty_rules_makes_everything_unknown(imported):
    assert _put(imported, []).status_code == 200
    body = imported.get("/api/categories").json()
    assert body["rules"] == []
    assert {x["category"] for x in body["search_names"]} == {"unknown"}


@pytest.mark.parametrize("body", [
    {},                                                          # no rules key
    {"rules": "obra nueva"},                                     # not a list
    {"rules": [{"contains": "x"}]},                              # category missing
    {"rules": [{"category": "flat"}]},                           # contains missing
    {"rules": [{"contains": "", "category": "flat"}]},           # empty contains
    {"rules": [{"contains": "x", "category": ""}]},              # empty category
    {"rules": [{"contains": 3, "category": "flat"}]},            # wrong type
    {"rules": ["obra nueva"]},                                   # not objects
    {"rules": [NEW_RULES[0], {"contains": "ok", "category": None}]},  # one bad rule spoils the whole save
])
def test_invalid_put_is_400_and_saves_nothing(imported, rules_path, body):
    file_before = rules_path.read_text(encoding="utf-8")
    api_before = imported.get("/api/categories").json()
    assert api_before["rules"] == START_RULES  # setup sanity: the route exists and answers 200

    resp = imported.put("/api/categories", json=body)
    assert resp.status_code == 400, resp.text
    assert rules_path.read_text(encoding="utf-8") == file_before
    assert imported.get("/api/categories").json() == api_before  # stored categories unchanged too


def test_put_does_not_touch_the_tracked_config(imported):
    before = TRACKED_RULES.read_bytes()
    assert _put(imported, NEW_RULES).status_code == 200
    assert TRACKED_RULES.read_bytes() == before


# ── PATCH new_build (FR-033, T035) ───────────────────────────────────────────────────────────────────
def _new_build(db_path, lid):
    with _db(db_path) as c:
        r = c.execute("SELECT new_build, new_build_origin FROM listings WHERE id=?", (lid,)).fetchone()
        return (r["new_build"], r["new_build_origin"])


def _chalet(db_path):
    """A listing from the chalets alerts whose emails do not state new-build (nothing to derive back)."""
    with _db(db_path) as c:
        ids = [r[0] for r in c.execute(
            "SELECT s.listing_id FROM sightings s JOIN alert_emails e ON e.email_id=s.email_id "
            "WHERE e.search_name='chalets en tu zona personalizada' GROUP BY s.listing_id "
            "HAVING MAX(COALESCE(s.new_build_stated, 0)) = 0 ORDER BY s.listing_id")]
    assert ids, "setup: a chalet listing with no new-build statement"
    return ids[0]


def _patch(client, lid, body):
    return client.patch(f"/api/listings/{lid}", json=body)


def test_patch_new_build_true_and_false_store_user_value(imported, db_path):
    lid = _chalet(db_path)
    assert _new_build(db_path, lid) == (None, None)   # setup: unknown, nothing imputed
    assert _patch(imported, lid, {"new_build": True}).status_code == 200
    assert _new_build(db_path, lid) == (1, "user")
    assert _patch(imported, lid, {"new_build": False}).status_code == 200
    assert _new_build(db_path, lid) == (0, "user")    # 'no' is a user statement, kept as 0 not null


def test_patch_new_build_null_clears_the_user_value(imported, db_path):
    lid = _chalet(db_path)
    assert _patch(imported, lid, {"new_build": True}).status_code == 200
    assert _new_build(db_path, lid) == (1, "user")
    assert _patch(imported, lid, {"new_build": None}).status_code == 200
    assert _new_build(db_path, lid) == (None, None)


def test_patch_new_build_null_lets_the_email_statement_back_in(imported, db_path):
    with _db(db_path) as c:
        stated = [r[0] for r in c.execute("SELECT DISTINCT listing_id FROM sightings WHERE new_build_stated=1")]
    if not stated:
        pytest.skip("no fixture sighting states new-build")  # the clearing rule is covered by the chalet test
    lid = stated[0]
    assert _patch(imported, lid, {"new_build": False}).status_code == 200
    assert _new_build(db_path, lid) == (0, "user")
    assert _patch(imported, lid, {"new_build": None}).status_code == 200
    assert _new_build(db_path, lid) == (1, "email")   # data-model: an email statement applies once no user value exists


@pytest.mark.parametrize("value", ["yes", 1, 0, "true", []])
def test_patch_new_build_rejects_non_boolean(imported, db_path, value):
    lid = _chalet(db_path)
    assert _patch(imported, lid, {"new_build": True}).status_code == 200   # setup sanity: field accepted at all
    resp = _patch(imported, lid, {"new_build": value})
    assert resp.status_code == 400, resp.text
    assert _new_build(db_path, lid) == (1, "user")   # unchanged


def test_patch_new_build_unknown_listing_is_404(imported):
    assert _patch(imported, "idealista:does-not-exist", {"new_build": True}).status_code == 404
