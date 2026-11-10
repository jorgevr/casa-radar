"""Malformed alert-category rules file (T034 fix loop 1, review T034-r1 finding 1).

Required behaviour (Article I: unexpected shapes fail with evidence, nothing silently dropped):
  * load_rules raises ONE ValueError whose message names the rules file and, for a bad entry, its 1-based
    position in the list and what was wrong. Covered: a typo'd key, a missing `contains`, a missing
    `category`, values that are not non-empty strings, a non-mapping entry, a top-level non-list, a YAML
    syntax error and a non-UTF-8 file.
  * A missing file, an empty file and `[]` still mean "no rules": categorise gives ('unknown', []).
  * categorise() and recategorise_all(conn) surface the error; recategorise_all writes nothing when it raises.
  * A valid file behaves as before.
Every expected value is written by hand from the rules in each test (Article VII).
"""
import pytest
import yaml

from app import categories, derive, zones

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


def _msg_without_path(exc, path):
    """The message with the file's full path removed, so digits in tmp_path cannot fake a position."""
    return str(exc.value).replace(str(path), "")


def _bad_third_entry(rules_path, bad):
    """Two valid rules, then `bad` as the 3rd entry; checks the ValueError names the file and position 3."""
    _write(rules_path, [OK1, OK2, bad])
    with pytest.raises(ValueError) as exc:
        categories.load_rules()
    assert rules_path.name in str(exc.value)
    assert "3" in _msg_without_path(exc, rules_path)  # 1-based position of the bad entry


# -- bad entries: position + file name ------------------------------------------------------------------
def test_typo_key_is_an_error_not_a_silent_drop(rules_path):
    _bad_third_entry(rules_path, {"contains": "pisos", "categroy": "flat"})


def test_typo_key_no_longer_changes_the_category(rules_path):
    # Review example: the typo'd rule used to vanish and 'Pisos y casas' was labelled 'house'.
    _write(rules_path, [{"contains": "pisos", "categroy": "flat"}, OK2])
    with pytest.raises(ValueError) as exc:
        categories.categorise("Pisos y casas 123")
    assert rules_path.name in str(exc.value)
    assert "1" in _msg_without_path(exc, rules_path)


def test_missing_contains_is_an_error(rules_path):
    _bad_third_entry(rules_path, {"category": "flat"})


def test_missing_category_is_an_error(rules_path):
    _bad_third_entry(rules_path, {"contains": "pisos"})


@pytest.mark.parametrize("bad", [
    {"contains": "", "category": "flat"},
    {"contains": "pisos", "category": ""},
    {"contains": "   ", "category": "flat"},
    {"contains": None, "category": "flat"},
    {"contains": "pisos", "category": None},
    {"contains": 5, "category": "flat"},
    {"contains": "pisos", "category": ["flat"]},
    {"contains": ["pisos"], "category": "flat"},
])
def test_values_must_be_non_empty_strings(rules_path, bad):
    _bad_third_entry(rules_path, bad)


@pytest.mark.parametrize("bad", ["foo", 7, None, ["contains", "category"]])
def test_non_mapping_entry_is_an_error(rules_path, bad):
    _bad_third_entry(rules_path, bad)


# -- whole-file problems: file name ---------------------------------------------------------------------
@pytest.mark.parametrize("content", ["contains: pisos\ncategory: flat\n", "just a string\n", "42\n"])
def test_top_level_not_a_list_is_an_error(rules_path, content):
    rules_path.write_text(content, encoding="utf-8")
    with pytest.raises(ValueError) as exc:
        categories.load_rules()
    assert rules_path.name in str(exc.value)


def test_yaml_syntax_error_is_a_value_error(rules_path):
    rules_path.write_text("- contains: pisos\n  category: [flat\n- : :\n", encoding="utf-8")
    with pytest.raises(ValueError) as exc:
        categories.load_rules()
    assert rules_path.name in str(exc.value)


def test_non_utf8_file_is_a_value_error(rules_path):
    rules_path.write_bytes(b"- contains: pis\xe9s\n  category: flat\n\xff\xfe\x00")
    with pytest.raises(ValueError) as exc:
        categories.load_rules()
    assert rules_path.name in str(exc.value)


def test_categorise_surfaces_the_error_for_any_text(rules_path):
    rules_path.write_text("- contains: pisos\n  category: [flat\n", encoding="utf-8")
    with pytest.raises(ValueError):
        categories.categorise("Pisos en Getafe")


# -- unchanged behaviour (pass today) -------------------------------------------------------------------
def test_missing_file_is_no_rules(rules_path):
    assert not rules_path.exists()
    assert categories.load_rules() == []
    assert categories.categorise("Pisos en Getafe") == ("unknown", [])


@pytest.mark.parametrize("content", ["", "\n", "# only a comment\n", "[]\n"])
def test_empty_file_or_empty_list_is_no_rules(rules_path, content):
    rules_path.write_text(content, encoding="utf-8")
    assert categories.load_rules() == []
    assert categories.categorise("Pisos en Getafe") == ("unknown", [])


def test_valid_file_is_unaffected(rules_path):
    dup = {"contains": "Pisos", "category": "flat"}
    _write(rules_path, [OK1, dup, OK2])
    assert categories.load_rules() == [OK1, dup, OK2]
    # same-category duplicates are not a conflict; matched_rules are the texts as written, in file order
    assert categories.categorise("Pisos en Getafe") == ("flat", ["pisos", "Pisos"])
    assert categories.categorise("Pisos y casas") == ("unknown", ["pisos", "Pisos", "casas"])
    assert categories.categorise("Chalets") == ("unknown", [])


# -- recategorise_all: raises before any write ----------------------------------------------------------
def _snapshot(conn):
    return {t: [tuple(r) for r in conn.execute(f"SELECT * FROM {t} ORDER BY 1, 2").fetchall()]
            for t in ("alert_emails", "sightings", "listings")}


def _seed(conn):
    conn.execute("INSERT INTO alert_emails(email_id, origin, subject, search_name, alert_date, alert_type, outcome, "
                 "category, category_rules_matched) VALUES('<e1@x>', 'file', 'Nuevo piso', 'Pisos en Getafe', "
                 "'2026-10-23', 'new_listing', 'imported', 'stale', '[\"stale\"]')")
    conn.execute("INSERT INTO sightings(email_id, listing_id, alert_type, seen_at, development, price, area_m2, "
                 "property_type, location_text, category, link_tracking, link_direct) VALUES('<e1@x>', "
                 "'idealista:1', 'new_listing', '2026-10-23T10:00:00+02:00', 0, 300000, 100, 'piso', 'Getafe', "
                 "'stale', 'https://www.idealista.com/inmueble/1/?x=1', 'https://www.idealista.com/inmueble/1/')")
    derive.derive_listing(conn, "idealista:1")
    conn.commit()


@pytest.mark.parametrize("content", [
    "- contains: pisos\n  categroy: flat\n",
    "contains: pisos\n",
    "- contains: pisos\n  category: [flat\n",
])
def test_recategorise_all_raises_and_changes_nothing(conn, rules_path, content):
    _seed(conn)
    before = _snapshot(conn)
    assert before["alert_emails"] and before["sightings"] and before["listings"]
    rules_path.write_text(content, encoding="utf-8")
    with pytest.raises(ValueError) as exc:
        categories.recategorise_all(conn)
    assert rules_path.name in str(exc.value)
    assert _snapshot(conn) == before
    assert conn.execute("SELECT category FROM alert_emails").fetchone()[0] == "stale"
