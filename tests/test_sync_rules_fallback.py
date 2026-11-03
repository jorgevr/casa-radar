"""Malformed category rules and every path that processes emails (follow-up FU4).

State of the code when these tests were written: the only caller of alerts.process_message is
alerts.import_paths (FU1 makes it load the rules once and fall back to 'unknown'). The mailbox sync (Phase 9)
does not exist yet, so its future loop is specified here at process_message level: a caller that does not pass
`rules` (the shape a sync loop has today) must not abort on a malformed rules file; the email is stored as
'unknown' with no matched rules. Rules are loaded once per run by import_paths (regression guard).
Expected values are written by hand from the rules in each test (Article VII). No network.
"""
import pytest
import yaml

from app import alerts, categories, zones

from .conftest import EMAILS

FIXTURES = [
    "2026-10-22_nueva-obra-nueva_obra-nueva-en-tu-zona-personalizada_112882173.eml",
    "2026-10-23_bajada-de-precio_viviendas-en-tu-zona-personalizada_112658090.eml",
    "2026-10-27_nuevo-chalet-pareado_chalets-en-tu-zona-personalizada_112923327.eml",
]
BAD_YAML = "- contains: pisos\n  category: [unclosed\n"


@pytest.fixture(autouse=True)
def no_aliases(tmp_path, monkeypatch):
    monkeypatch.setattr(zones, "ALIASES_PATH", tmp_path / "zone_aliases.yaml")


@pytest.fixture
def rules_path(tmp_path, monkeypatch, no_network):
    path = tmp_path / "alert_categories.yaml"
    monkeypatch.setattr(categories, "CATEGORIES_PATH", path)
    return path


def _process_all_without_rules(conn):
    """What a per-message caller without a pre-loaded rule set does."""
    run_id = alerts.start_run(conn, "mailbox_sync")
    outs = [alerts.process_message(conn, (EMAILS / n).read_bytes(), origin="mailbox", mailbox_id=f"m{i}",
                                   run_id=run_id) for i, n in enumerate(FIXTURES)]
    return run_id, outs


def test_process_message_without_rules_on_malformed_file_stores_unknown(conn, rules_path):
    rules_path.write_text(BAD_YAML, encoding="utf-8")

    _, outs = _process_all_without_rules(conn)  # must not raise

    assert [o.outcome for o in outs] == ["imported"] * 3  # none lost
    rows = conn.execute("SELECT category, category_rules_matched FROM alert_emails").fetchall()
    assert len(rows) == 3
    assert {r["category"] for r in rows} == {"unknown"}
    assert {r["category_rules_matched"] for r in rows} == {"[]"}


def test_process_message_without_rules_on_unreadable_file_stores_unknown(conn, rules_path):
    rules_path.mkdir()  # a directory where the file should be: OSError while reading

    _, outs = _process_all_without_rules(conn)

    assert [o.outcome for o in outs] == ["imported"] * 3
    assert {r[0] for r in conn.execute("SELECT category FROM alert_emails")} == {"unknown"}


def test_process_message_without_rules_still_uses_a_valid_file(conn, rules_path):
    # Guard: the fallback must not turn valid rules off. 'chalets' is in the search name of the third fixture's
    # alert (see test_categories_rules_file); here we only require the rule to be applied when it matches.
    rules_path.write_text(yaml.safe_dump([{"contains": "chalet", "category": "villa"}]), encoding="utf-8")

    _process_all_without_rules(conn)

    cats = {r[0] for r in conn.execute("SELECT category FROM alert_emails")}
    assert "villa" in cats


def test_import_paths_loads_rules_once_per_run(conn, rules_path, monkeypatch):
    rules_path.write_text(yaml.safe_dump([{"contains": "pisos", "category": "flat"}]), encoding="utf-8")
    real, calls = categories.load_rules, []
    monkeypatch.setattr(categories, "load_rules", lambda: calls.append(1) or real())

    summary = alerts.import_paths(conn, [EMAILS / n for n in FIXTURES])

    assert summary["n_found"] == 3
    assert len(calls) == 1  # three emails, one load


def test_import_paths_with_malformed_rules_loads_once_and_error_has_no_local_path(conn, rules_path, tmp_path,
                                                                                    monkeypatch):
    rules_path.write_text(BAD_YAML, encoding="utf-8")
    real, calls = categories.load_rules, []
    monkeypatch.setattr(categories, "load_rules", lambda: calls.append(1) or real())

    summary = alerts.import_paths(conn, [EMAILS / n for n in FIXTURES])

    assert len(calls) == 1
    run = conn.execute("SELECT status, error FROM import_runs WHERE run_id=?", (summary["run_id"],)).fetchone()
    assert run["status"] == "ok"
    assert run["error"].startswith("ValueError: ") and rules_path.name in run["error"]
    assert str(tmp_path) not in run["error"] and str(tmp_path.parent) not in run["error"]
