"""Alert categories, unit and derivation level (T031 part 1; implemented by T033 + T034; no HTTP API).

Spec: FR-031 (rules "subject contains <text> -> <category>", case and accent insensitive, no match or
conflicting matches -> "unknown", changing rules re-derives every stored email), FR-032 (category stored on
the sighting, listing shows "found via" every category it was seen under, a category never sets or changes
the property type), FR-033 (new-build category only as a flag to confirm), data-model.md (alert_emails.category,
category_rules_matched, sightings.category, listings.categories, Flag texts), research R12.

Interface assumed (tasks.md T033; the task does not fix the path mechanism, so this file fixes it):
  * app.categories.CATEGORIES_PATH   module attribute, a path to the rules YAML, read at call time (like
                                     zones.ALIASES_PATH); tests point it at tmp_path, never at config/.
  * app.categories.categorise(text)  -> (category, matched_rules), `text` = subject or search name.
  * app.categories.recategorise_all(conn)
  * file format = the tracked config/alert_categories.yaml: a YAML list of {contains, category}.
  * matched_rules = list of the matching rules' `contains` text exactly as written in the file, in file order
    (also what is stored, as a JSON list, in alert_emails.category_rules_matched).
  * listings.categories = JSON list of the distinct sighting categories, alphabetical.
  * Flags are read through scoring.rank(...)[i]["eval"]["flags"] (T034 puts them in scoring); the conflict
    flag joins the rule texts with ", ".

Every expected value below is written by hand from the rules in each test (Article VII).
"""
import importlib
import json

import pytest
import yaml

from app import derive, scoring, zones


@pytest.fixture(autouse=True)
def no_aliases(tmp_path, monkeypatch):
    monkeypatch.setattr(zones, "ALIASES_PATH", tmp_path / "zone_aliases.yaml")


@pytest.fixture
def cats(tmp_path, monkeypatch, no_network):
    """app.categories pointed at a rules file in tmp_path; `cats.set_rules([...])` rewrites that file."""
    mod = importlib.import_module("app.categories")  # missing until T033: one clear failure per test
    path = tmp_path / "alert_categories.yaml"
    monkeypatch.setattr(mod, "CATEGORIES_PATH", path)

    def set_rules(rules):
        path.write_text(yaml.safe_dump(rules, allow_unicode=True, sort_keys=False), encoding="utf-8")

    mod.set_rules = set_rules
    return mod


def _email(conn, email_id, search_name, alert_date, stale_category="stale"):
    """A stored alert whose category is deliberately wrong, so only a re-derivation can fix it."""
    subject = f"¡Nuevo piso en tu búsqueda: {search_name}!"
    conn.execute("INSERT INTO alert_emails(email_id, origin, subject, search_name, alert_date, alert_type, outcome, "
                 "category, category_rules_matched) VALUES(?, 'file', ?, ?, ?, 'new_listing', 'imported', ?, '[\"stale\"]')",
                 (email_id, subject, search_name, alert_date, stale_category))


def _sighting(conn, email_id, code, seen_at, **fields):
    lid = f"idealista:{code}"
    row = {"email_id": email_id, "listing_id": lid, "alert_type": "new_listing", "seen_at": seen_at,
           "development": 0, "price": 300_000, "area_m2": 100, "property_type": "piso", "location_text": "Getafe",
           "category": "stale", "link_tracking": f"https://www.idealista.com/inmueble/{code}/?x=1",
           "link_direct": f"https://www.idealista.com/inmueble/{code}/", **fields}
    conn.execute(f"INSERT INTO sightings({','.join(row)}) VALUES({','.join('?' * len(row))})", list(row.values()))
    return lid


def _listing(conn, lid):
    return conn.execute("SELECT * FROM listings WHERE id=?", (lid,)).fetchone()


def _flags(conn, needs, lid):
    return next(r for r in scoring.rank(conn, needs) if r["id"] == lid)["eval"]["flags"]


def _stored_email(conn, email_id):
    r = conn.execute("SELECT category, category_rules_matched FROM alert_emails WHERE email_id=?",
                     (email_id,)).fetchone()
    return r["category"], json.loads(r["category_rules_matched"])


# ── categorise(): matching ────────────────────────────────────────────────────────────────────────────
def test_match_ignores_case_and_accents(cats):
    cats.set_rules([{"contains": "Ático DÚPLEX en Getafe", "category": "penthouse"}])
    # subject text has other case and no accents; both sides are compared as slug() forms
    assert cats.categorise("¡Nuevo piso en tu búsqueda: ATICO duplex EN getafe!") == (
        "penthouse", ["Ático DÚPLEX en Getafe"])


def test_match_is_substring_of_the_whole_text(cats):
    cats.set_rules([{"contains": "obra nueva en tu zona personalizada", "category": "new-build"}])
    assert cats.categorise("¡Nueva obra nueva en tu búsqueda: Obra nueva en tu zona personalizada!") == (
        "new-build", ["obra nueva en tu zona personalizada"])
    # a bare search name works too (task: subject_or_search_name)
    assert cats.categorise("Obra nueva en tu zona personalizada")[0] == "new-build"


def test_no_match_is_unknown_with_no_rules_listed(cats):
    cats.set_rules([{"contains": "chalets en tu zona personalizada", "category": "house"}])
    assert cats.categorise("¡Nuevo piso en tu búsqueda: Viviendas en tu zona personalizada!") == ("unknown", [])


def test_no_rules_and_empty_text_are_unknown(cats):
    cats.set_rules([])
    assert cats.categorise("anything") == ("unknown", [])
    cats.set_rules([{"contains": "chalets", "category": "house"}])
    assert cats.categorise("") == ("unknown", [])
    assert cats.categorise(None) == ("unknown", [])


def test_two_rules_with_different_categories_conflict(cats):
    cats.set_rules([{"contains": "zona personalizada", "category": "house"},
                    {"contains": "obra nueva", "category": "new-build"},
                    {"contains": "chalets", "category": "house"}])
    # matches the first two (house vs new-build): conflict, both listed in file order; "chalets" does not match
    assert cats.categorise("Obra nueva en tu zona personalizada") == (
        "unknown", ["zona personalizada", "obra nueva"])


def test_two_rules_with_the_same_category_do_not_conflict(cats):
    cats.set_rules([{"contains": "chalets", "category": "house"},
                    {"contains": "zona personalizada", "category": "house"}])
    assert cats.categorise("chalets en tu zona personalizada") == ("house", ["chalets", "zona personalizada"])


def test_rules_are_read_at_call_time(cats):
    cats.set_rules([{"contains": "pisos", "category": "flat"}])
    assert cats.categorise("pisos en getafe")[0] == "flat"
    cats.set_rules([{"contains": "pisos", "category": "apartment"}])
    assert cats.categorise("pisos en getafe")[0] == "apartment"


# ── recategorise_all(): stored emails, sightings, listings ───────────────────────────────────────────
@pytest.fixture
def stored(conn, cats):
    """Three alerts; L1 seen in the apartments and new-build alerts, L2 only in the 'Viviendas' alert.

    e1 'Viviendas en tu zona personalizada' -> L2
    e2 'apartamentos en tu zona personalizada' -> L1
    e3 'Obra nueva en tu zona personalizada' -> L1
    Dates: e2 older than e3, so alphabetical and first-seen order of L1's categories agree.
    """
    _email(conn, "<e1@x>", "Viviendas en tu zona personalizada", "2026-10-23")
    _email(conn, "<e2@x>", "apartamentos en tu zona personalizada", "2026-10-24")
    _email(conn, "<e3@x>", "Obra nueva en tu zona personalizada", "2026-10-25")
    l2 = _sighting(conn, "<e1@x>", "2002", "2026-10-23T10:00:00+02:00")
    l1 = _sighting(conn, "<e2@x>", "2001", "2026-10-24T10:00:00+02:00")
    _sighting(conn, "<e3@x>", "2001", "2026-10-25T10:00:00+02:00")
    for lid in (l1, l2):
        derive.derive_listing(conn, lid)
    conn.commit()
    return {"L1": l1, "L2": l2}


def test_recategorise_updates_emails_sightings_and_listings(conn, cats, stored):
    cats.set_rules([{"contains": "apartamentos en tu zona personalizada", "category": "flat"},
                    {"contains": "obra nueva en tu zona personalizada", "category": "new-build"}])
    cats.recategorise_all(conn)

    assert _stored_email(conn, "<e1@x>") == ("unknown", [])          # 'Viviendas...' matches no rule
    assert _stored_email(conn, "<e2@x>") == ("flat", ["apartamentos en tu zona personalizada"])
    assert _stored_email(conn, "<e3@x>") == ("new-build", ["obra nueva en tu zona personalizada"])

    cat = {(r["email_id"], r["listing_id"]): r["category"] for r in conn.execute("SELECT * FROM sightings")}
    assert cat == {("<e1@x>", stored["L2"]): "unknown", ("<e2@x>", stored["L1"]): "flat",
                   ("<e3@x>", stored["L1"]): "new-build"}

    assert json.loads(_listing(conn, stored["L1"])["categories"]) == ["flat", "new-build"]
    assert json.loads(_listing(conn, stored["L2"])["categories"]) == ["unknown"]


def test_changing_rules_and_recategorising_again_rederives_everything(conn, cats, stored):
    cats.set_rules([{"contains": "apartamentos en tu zona personalizada", "category": "flat"},
                    {"contains": "obra nueva en tu zona personalizada", "category": "new-build"}])
    cats.recategorise_all(conn)
    # new rules: every search name now says "zona personalizada" -> house, except the apartments one -> flat
    cats.set_rules([{"contains": "zona personalizada", "category": "house"},
                    {"contains": "apartamentos", "category": "flat"}])
    cats.recategorise_all(conn)

    # e2 matches both rules (house vs flat): conflict -> unknown, both rules listed in file order
    assert _stored_email(conn, "<e2@x>") == ("unknown", ["zona personalizada", "apartamentos"])
    assert _stored_email(conn, "<e1@x>") == ("house", ["zona personalizada"])
    assert _stored_email(conn, "<e3@x>") == ("house", ["zona personalizada"])
    assert json.loads(_listing(conn, stored["L2"])["categories"]) == ["house"]
    assert json.loads(_listing(conn, stored["L1"])["categories"]) == ["house", "unknown"]


def test_recategorise_is_idempotent(conn, cats, stored):
    cats.set_rules([{"contains": "obra nueva", "category": "new-build"}])
    cats.recategorise_all(conn)
    first = [tuple(r) for r in conn.execute("SELECT email_id, category, category_rules_matched FROM alert_emails ORDER BY 1")]
    cats.recategorise_all(conn)
    assert [tuple(r) for r in conn.execute(
        "SELECT email_id, category, category_rules_matched FROM alert_emails ORDER BY 1")] == first


# ── found-via and conflict flags (US1-9, FR-031, FR-032) ─────────────────────────────────────────────
def test_listing_seen_under_two_categories_lists_both_in_the_flag(conn, cats, needs, stored):
    cats.set_rules([{"contains": "apartamentos en tu zona personalizada", "category": "flat"},
                    {"contains": "obra nueva en tu zona personalizada", "category": "new-build"}])
    cats.recategorise_all(conn)
    flags = _flags(conn, needs, stored["L1"])
    assert "encontrado vía: flat, new-build" in flags


def test_listing_with_no_category_says_unknown_search(conn, cats, needs, stored):
    cats.set_rules([{"contains": "apartamentos en tu zona personalizada", "category": "flat"}])
    cats.recategorise_all(conn)
    flags = _flags(conn, needs, stored["L2"])
    assert "encontrado vía: búsqueda desconocida" in flags
    assert not any(f.startswith("reglas de categoría en conflicto") for f in flags)  # no rule matched at all


def test_conflicting_rules_flag_lists_the_rules(conn, cats, needs, stored):
    cats.set_rules([{"contains": "viviendas", "category": "flat"},
                    {"contains": "zona personalizada", "category": "house"}])
    cats.recategorise_all(conn)
    flags = _flags(conn, needs, stored["L2"])
    assert "reglas de categoría en conflicto: viviendas, zona personalizada" in flags
    assert "encontrado vía: búsqueda desconocida" in flags  # the category is 'unknown'


def test_no_category_flags_for_a_single_known_category(conn, cats, needs, stored):
    cats.set_rules([{"contains": "zona personalizada", "category": "house"}])
    cats.recategorise_all(conn)
    flags = _flags(conn, needs, stored["L2"])
    assert "encontrado vía: house" in flags
    assert "encontrado vía: búsqueda desconocida" not in flags


# ── a category never changes the property type (FR-032) ──────────────────────────────────────────────
def test_category_never_changes_property_type(conn, cats, stored):
    before = {k: _listing(conn, lid)["property_type"] for k, lid in stored.items()}
    assert before == {"L1": "piso", "L2": "piso"}  # from the sightings, set up above
    cats.set_rules([{"contains": "obra nueva", "category": "new-build"},
                    {"contains": "viviendas", "category": "house"},
                    {"contains": "apartamentos", "category": "flat"}])
    cats.recategorise_all(conn)
    assert {k: _listing(conn, lid)["property_type"] for k, lid in stored.items()} == before
    assert {r["property_type"] for r in conn.execute("SELECT property_type FROM sightings")} == {"piso"}


# ── new-build from category (FR-033, data-model) ─────────────────────────────────────────────────────
def test_new_build_category_sets_new_build_only_as_category_origin_with_flag(conn, cats, needs, stored):
    cats.set_rules([{"contains": "obra nueva", "category": "new-build"}])
    cats.recategorise_all(conn)
    row = _listing(conn, stored["L1"])   # seen in e3 (new-build); no sighting states new-build
    assert (row["new_build"], row["new_build_origin"]) == (1, "category")
    assert "obra nueva según la categoría de la alerta, confirma" in _flags(conn, needs, stored["L1"])
    other = _listing(conn, stored["L2"])  # only the unmatched 'Viviendas' alert: nothing is imputed
    assert (other["new_build"], other["new_build_origin"]) == (None, None)


def test_user_new_build_value_survives_recategorisation(conn, cats, stored):
    conn.execute("UPDATE listings SET new_build=0, new_build_origin='user' WHERE id=?", (stored["L1"],))
    conn.commit()
    cats.set_rules([{"contains": "obra nueva", "category": "new-build"}])
    cats.recategorise_all(conn)
    row = _listing(conn, stored["L1"])
    assert (row["new_build"], row["new_build_origin"]) == (0, "user")
