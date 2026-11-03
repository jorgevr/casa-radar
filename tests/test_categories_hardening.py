"""Hardening of the alert-category rules and of the import path (follow-up group FU1).

Required behaviour:
  * validate_rules / load_rules reject, with a ValueError naming the 1-based rule index: unknown extra keys in a
    rule; a key repeated inside one rule mapping (PyYAML would silently keep the last); a `contains` that is empty or reduces to
    nothing after slug() (e.g. only punctuation). The identical rules and the same `contains` with another category stay allowed
    (conflicts are designed: categorise gives 'unknown'). Whitespace around `category` is trimmed, on load,
    on validate and on save.
  * An OSError reading the rules file (a directory instead of a file) becomes a ValueError that names the file
    but not the full local path.
  * A malformed rules file does not abort an import run: each email is stored with category 'unknown', and
    import_runs.error holds "ValueError: <full message>". Status: the run completed, so 'ok' (the only
    statuses in use are running / ok / failed; 'failed' means the run aborted and re-raised).
Expected values are written by hand from the rules in each test (Article VII). No network.
"""
import pytest
import yaml

from app import alerts, categories, zones

from .conftest import EMAILS

OK1 = {"contains": "pisos", "category": "flat"}
OK2 = {"contains": "casas", "category": "house"}


@pytest.fixture(autouse=True)
def no_aliases(tmp_path, monkeypatch):
    monkeypatch.setattr(zones, "ALIASES_PATH", tmp_path / "zone_aliases.yaml")


@pytest.fixture
def rules_path(tmp_path, monkeypatch, no_network):
    path = tmp_path / "alert_categories.yaml"
    monkeypatch.setattr(categories, "CATEGORIES_PATH", path)
    return path


def _write(path, rules):
    path.write_text(yaml.safe_dump(rules, allow_unicode=True, sort_keys=False), encoding="utf-8")


def _bad_third(rules_path, rules):
    """`rules` has the offending entry as 3rd; load_rules must name the file and position 3."""
    _write(rules_path, rules)
    with pytest.raises(ValueError) as exc:
        categories.load_rules()
    assert rules_path.name in str(exc.value)
    assert "3" in str(exc.value).replace(str(rules_path), "")


# -- extra keys -------------------------------------------------------------------------------------------
def test_unknown_extra_key_is_rejected_on_load(rules_path):
    _bad_third(rules_path, [OK1, OK2, {"contains": "chalets", "category": "villa", "note": "x"}])


def test_unknown_extra_key_is_rejected_by_validate():
    with pytest.raises(ValueError) as exc:
        categories.validate_rules([OK1, {"contains": "casas", "category": "house", "extra": 1}])
    assert "2" in str(exc.value)


# -- duplicate keys inside one rule -----------------------------------------------------------------------
# PyYAML silently keeps the last value of a repeated key; the loader must reject it instead.
def test_repeated_key_inside_a_rule_is_rejected(rules_path):
    rules_path.write_text(
        "- contains: pisos\n  category: flat\n"
        "- contains: casas\n  category: house\n"
        "- contains: chalets\n  category: villa\n  category: chalet\n", encoding="utf-8")
    with pytest.raises(ValueError) as exc:
        categories.load_rules()
    msg = str(exc.value).replace(str(rules_path), "")
    assert rules_path.name in str(exc.value)
    assert "category" in msg  # the repeated key
    assert "3" in msg  # 1-based rule index


def test_repeated_contains_key_is_rejected(rules_path):
    rules_path.write_text("- contains: pisos\n  contains: casas\n  category: flat\n", encoding="utf-8")
    with pytest.raises(ValueError) as exc:
        categories.load_rules()
    assert "contains" in str(exc.value).replace(str(rules_path), "")


def test_same_contains_and_same_category_still_loads(rules_path):
    # Not a duplicate-key problem: two separate rules may be identical (test_categories_rules_file relies on it)
    _write(rules_path, [OK1, dict(OK1)])
    assert categories.load_rules() == [OK1, OK1]


def test_same_contains_with_other_category_is_allowed(rules_path):
    _write(rules_path, [OK1, {"contains": "pisos", "category": "house"}])
    assert len(categories.load_rules()) == 2
    assert categories.categorise("Pisos baratos") == ("unknown", ["pisos", "pisos"])


# -- contains that reduces to nothing --------------------------------------------------------------------
@pytest.mark.parametrize("contains", ["", "   ", "¿?!", "---", " . , "])
def test_contains_that_reduces_to_nothing_is_rejected(rules_path, contains):
    _bad_third(rules_path, [OK1, OK2, {"contains": contains, "category": "flat"}])


def test_accented_contains_that_slugs_to_something_is_allowed(rules_path):
    _write(rules_path, [{"contains": "Ático", "category": "penthouse"}])
    assert categories.load_rules()[0]["category"] == "penthouse"


# -- trimming ---------------------------------------------------------------------------------------------
def test_category_is_trimmed_on_load(rules_path):
    _write(rules_path, [{"contains": "pisos", "category": "  flat \t"}])
    assert categories.load_rules()[0]["category"] == "flat"
    assert categories.categorise("Pisos") == ("flat", ["pisos"])


def test_category_is_trimmed_by_validate():
    assert categories.validate_rules([{"contains": "pisos", "category": " flat "}])[0]["category"] == "flat"


def test_category_is_trimmed_on_save(rules_path):
    categories.save_rules([{"contains": "pisos", "category": " flat "}])
    assert yaml.safe_load(rules_path.read_text(encoding="utf-8")) == [{"contains": "pisos", "category": "flat"}]


# -- OSError reading the file ----------------------------------------------------------------------------
def test_unreadable_rules_file_is_a_valueerror_without_full_path(tmp_path, monkeypatch, no_network):
    folder = tmp_path / "private_dir" / "alert_categories.yaml"
    folder.mkdir(parents=True)  # a directory where the file should be: open() raises OSError
    monkeypatch.setattr(categories, "CATEGORIES_PATH", folder)
    with pytest.raises(ValueError) as exc:
        categories.load_rules()
    assert "alert_categories.yaml" in str(exc.value)
    assert str(tmp_path) not in str(exc.value)
    assert "private_dir" not in str(exc.value)


# -- import keeps going with a malformed rules file -------------------------------------------------------
IMPORT_FIXTURES = [
    "2026-10-22_nueva-obra-nueva_obra-nueva-en-tu-zona-personalizada_112882173.eml",
    "2026-10-23_bajada-de-precio_viviendas-en-tu-zona-personalizada_112658090.eml",
    "2026-10-27_nuevo-chalet-pareado_chalets-en-tu-zona-personalizada_112923327.eml",
]


def test_import_with_malformed_rules_stores_emails_as_unknown_and_records_error(conn, rules_path):
    rules_path.write_text("- contains: pisos\n  category: [unclosed\n", encoding="utf-8")

    summary = alerts.import_paths(conn, [EMAILS / n for n in IMPORT_FIXTURES])  # must not raise

    # three alert fixtures (same three as test_alerts_import.MBOX_FIXTURES): all imported, none lost
    assert (summary["n_found"], summary["n_imported"], summary["n_failed"]) == (3, 3, 0)
    rows = conn.execute("SELECT category, category_rules_matched FROM alert_emails").fetchall()
    assert len(rows) == 3
    assert {r["category"] for r in rows} == {"unknown"}
    assert {r["category_rules_matched"] for r in rows} == {"[]"}
    assert {r[0] for r in conn.execute("SELECT category FROM sightings")} == {"unknown"}

    run = conn.execute("SELECT status, error FROM import_runs WHERE run_id=?", (summary["run_id"],)).fetchone()
    assert run["status"] == "ok"  # the run completed; the problem is reported in `error`
    assert run["error"].startswith("ValueError: ")
    assert rules_path.name in run["error"]
    assert "invalid YAML" in run["error"]


def test_import_with_valid_rules_leaves_error_empty(conn, rules_path):
    _write(rules_path, [OK1])
    summary = alerts.import_paths(conn, [EMAILS / IMPORT_FIXTURES[0]])
    run = conn.execute("SELECT status, error FROM import_runs WHERE run_id=?", (summary["run_id"],)).fetchone()
    assert (run["status"], run["error"]) == ("ok", None)


# -- no absolute path in YAML / UTF-8 errors (review 1, F1) -----------------------------------------------
def _assert_name_only(text, rules_path, tmp_path):
    assert rules_path.name in text
    assert str(tmp_path) not in text
    assert str(tmp_path.parent) not in text


def test_invalid_yaml_error_names_file_but_not_its_directory(rules_path, tmp_path):
    rules_path.write_text("- contains: pisos\n  category: [unclosed\n", encoding="utf-8")
    with pytest.raises(ValueError) as exc:
        categories.load_rules()
    assert "invalid YAML" in str(exc.value)
    _assert_name_only(str(exc.value), rules_path, tmp_path)  # PyYAML marks embed the path too


def test_invalid_utf8_error_names_file_but_not_its_directory(rules_path, tmp_path):
    rules_path.write_bytes(b"- contains: pisos\n  category: fl\xff\xfeat\n")
    with pytest.raises(ValueError) as exc:
        categories.load_rules()
    assert "UTF-8" in str(exc.value)
    _assert_name_only(str(exc.value), rules_path, tmp_path)


def test_entry_error_names_file_but_not_its_directory(rules_path, tmp_path):
    _write(rules_path, [OK1, {"contains": "casas"}])
    with pytest.raises(ValueError) as exc:
        categories.load_rules()
    _assert_name_only(str(exc.value), rules_path, tmp_path)


def test_import_error_column_has_no_absolute_path(conn, rules_path, tmp_path):
    rules_path.write_text("- contains: pisos\n  category: [unclosed\n", encoding="utf-8")
    summary = alerts.import_paths(conn, [EMAILS / IMPORT_FIXTURES[0]])
    error = conn.execute("SELECT error FROM import_runs WHERE run_id=?", (summary["run_id"],)).fetchone()["error"]
    assert error.startswith("ValueError: ")
    _assert_name_only(error, rules_path, tmp_path)
