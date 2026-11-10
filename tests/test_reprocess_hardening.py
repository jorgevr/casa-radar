"""Re-process hardening (FU5; review T044 findings F1, F2, F4, F5). F3 is not specified here (needs a user decision).

  F1  GET /api/runs/{id} of a reprocess run lists its failed/rejected emails in `problems`. Reprocess keeps
      first_run_id and sets only last_run_id, so the query must follow last_run_id for kind "reprocess".
      Import runs keep listing by first_run_id (pin).
  F2  A malformed categories file must not overwrite stored categories: each re-read email keeps its category,
      and the run records "ValueError: <file name only message>" in import_runs.error (no local path).
      Run status follows the import convention (ok, with the note).
  F4  Scope "failed" selects emails whose reader_version DIFFERS from the current one (or is NULL), not those
      "smaller" as strings: "idealista-2026.9" sorts after "idealista-2026.10".
  F5  An unexpected exception while re-reading one email does not abort the run: that email keeps its state, is
      counted failed with the exception class as reason (never the message), later emails are still processed,
      and n_imported + n_rejected + n_failed + n_already == n_found.

Stored emails are the anonymised fixtures mutated in memory (reprocess_support). Expected values are by hand:
  * OTHER_DROP (112658090) 2026-10-23, DROP (112842548) 2026-10-26, NEW 2026-10-27: reprocess order is by
    alert date, so OTHER_DROP, DROP, NEW.
  * the DROP fixture's search name contains "chalets" (file name "chalets-en-tu-zona-personalizada").
"""
import base64

import pytest
from fastapi.testclient import TestClient

from app import alerts, categories, zones
from app.main import create_app
from app.providers import idealista_alert as reader

from .conftest import EXAMPLE_NEEDS
from .reprocess_support import DROP_NAME, NEW_NAME, OTHER_DROP_NAME, fixture, message_id, store, table, truncated

CURRENT = "idealista-2026.10"


@pytest.fixture(autouse=True)
def no_aliases(tmp_path, monkeypatch):
    monkeypatch.setattr(zones, "ALIASES_PATH", tmp_path / "zone_aliases.yaml")


@pytest.fixture
def current_reader(monkeypatch):
    monkeypatch.setattr(reader, "READER_VERSION", CURRENT)


def _row(conn, email_id):
    return dict(conn.execute("SELECT * FROM alert_emails WHERE email_id=?", (email_id,)).fetchone())


# -- F1 -----------------------------------------------------------------------------------------------
@pytest.fixture
def client(tmp_path):
    needs = tmp_path / "needs.yaml"
    needs.write_text(EXAMPLE_NEEDS.read_text(encoding="utf-8"), encoding="utf-8")
    with TestClient(create_app(str(tmp_path / "t.db"), str(needs))) as c:
        yield c


def _import(client, raws):
    files = [{"name": f"m{i}.eml", "content_base64": base64.b64encode(r).decode("ascii")}
             for i, r in enumerate(raws)]
    resp = client.post("/api/alerts/import", json={"files": files})
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_reprocess_run_detail_lists_its_problems(client, no_network):
    broken = truncated(fixture(DROP_NAME), "broken-1")
    imported = _import(client, [broken, fixture(NEW_NAME)])
    assert (imported["n_failed"], imported["n_imported"]) == (1, 1)

    resp = client.post("/api/alerts/reprocess", json={"scope": "all"})  # the broken one fails again
    assert resp.status_code == 200, resp.text
    summary = resp.json()
    assert (summary["n_found"], summary["n_failed"]) == (2, 1)
    assert [p["email_id"] for p in summary["problems"]] == ["<broken-1@example.invalid>"]

    detail = client.get(f"/api/runs/{summary['run_id']}").json()
    assert detail["kind"] == "reprocess" and detail["n_failed"] == 1
    assert [(p["email_id"], p["outcome"]) for p in detail["problems"]] == [("<broken-1@example.invalid>", "failed")]
    assert "0 tarjetas" in detail["problems"][0]["reason"]


def test_import_run_detail_still_lists_its_problems(client, no_network):
    """Pin: import runs list by first_run_id, also after a later reprocess touched the same email."""
    imported = _import(client, [truncated(fixture(DROP_NAME), "broken-1"), fixture(NEW_NAME)])
    client.post("/api/alerts/reprocess", json={"scope": "all"})
    detail = client.get(f"/api/runs/{imported['run_id']}").json()
    assert [p["email_id"] for p in detail["problems"]] == ["<broken-1@example.invalid>"]


# -- F2 -----------------------------------------------------------------------------------------------
def test_malformed_categories_file_keeps_stored_categories(conn, tmp_path, monkeypatch, no_network, current_reader):
    rules_path = tmp_path / "alert_categories.yaml"
    monkeypatch.setattr(categories, "CATEGORIES_PATH", rules_path)
    rules_path.write_text("- contains: chalets\n  category: house\n", encoding="utf-8")
    (out,) = store(conn, [fixture(DROP_NAME)])
    assert out.outcome == "imported"
    before = _row(conn, out.email_id)
    assert before["category"] == "house"  # precondition: the rule matched at import
    assert table(conn, "SELECT category FROM sightings") == [{"category": "house"}]

    rules_path.write_text("- contains: [unclosed\n  category: house\n", encoding="utf-8")  # malformed YAML
    with pytest.raises(ValueError):  # precondition: the loader really rejects it
        categories.load_rules()

    summary = alerts.reprocess(conn, scope="all")

    assert summary["n_found"] == 1 and summary["n_imported"] == 1
    after = _row(conn, out.email_id)
    assert after["category"] == "house"
    assert after["category_rules_matched"] == before["category_rules_matched"]
    assert table(conn, "SELECT category FROM sightings") == [{"category": "house"}]
    assert summary["status"] == "ok"  # same convention as import: the problem is recorded, not fatal
    error = conn.execute("SELECT error FROM import_runs WHERE run_id=?", (summary["run_id"],)).fetchone()[0]
    assert error.startswith("ValueError: ") and "alert_categories.yaml" in error
    assert str(tmp_path) not in error  # file name only, no local path


# -- F4 -----------------------------------------------------------------------------------------------
def test_failed_scope_compares_versions_by_difference_not_string_order(conn, no_network, current_reader):
    older, same, missing = (truncated(fixture(DROP_NAME), tag) for tag in ("old-1", "same-1", "null-1"))
    outs = store(conn, [older, same, missing])
    assert [o.outcome for o in outs] == ["failed"] * 3
    old_id, same_id, null_id = (o.email_id for o in outs)
    assert "idealista-2026.9" > CURRENT  # why a string comparison would skip it
    conn.execute("UPDATE alert_emails SET reader_version='idealista-2026.9' WHERE email_id=?", (old_id,))
    conn.execute("UPDATE alert_emails SET reader_version=NULL WHERE email_id=?", (null_id,))
    conn.commit()
    same_before = _row(conn, same_id)

    summary = alerts.reprocess(conn, scope="failed")

    assert summary["n_found"] == 2  # the 2026.9 one and the NULL one; the current-version one is left alone
    for email_id in (old_id, null_id):
        assert _row(conn, email_id)["reader_version"] == CURRENT
        assert _row(conn, email_id)["last_run_id"] == summary["run_id"]
    assert _row(conn, same_id) == same_before


# -- F5 -----------------------------------------------------------------------------------------------
def test_unexpected_reader_exception_does_not_abort_the_run(conn, monkeypatch, no_network, current_reader):
    raws = [fixture(OTHER_DROP_NAME), fixture(DROP_NAME), fixture(NEW_NAME)]  # alert dates 10-23, 10-26, 10-27
    outs = store(conn, raws)
    assert [o.outcome for o in outs] == ["imported"] * 3
    first, boom, last = (o.email_id for o in outs)
    assert boom == message_id(raws[1])
    boom_before = _row(conn, boom)
    boom_sightings = table(conn, "SELECT * FROM sightings WHERE email_id=?", boom)
    assert boom_sightings  # precondition

    original = reader.read

    def flaky(msg):
        if str(msg["Message-ID"]) == boom:
            raise RuntimeError("secret-detail-from-the-reader")
        return original(msg)

    monkeypatch.setattr(reader, "read", flaky)

    summary = alerts.reprocess(conn, scope="all")  # must not raise

    assert summary["n_found"] == 3
    assert (summary["n_imported"], summary["n_failed"], summary["n_rejected"]) == (2, 1, 0)
    assert (summary["n_imported"] + summary["n_rejected"] + summary["n_failed"] + summary["n_already"]
            == summary["n_found"])
    assert _row(conn, first)["last_run_id"] == summary["run_id"]  # before the failing one
    assert _row(conn, last)["last_run_id"] == summary["run_id"]  # and after it: still processed
    # the failing email keeps its previous state, including its sightings
    boom_after = _row(conn, boom)
    for col in ("outcome", "reason", "reader_version", "category", "alert_type", "search_name", "raw", "content_hash"):
        assert boom_after[col] == boom_before[col], col
    assert table(conn, "SELECT * FROM sightings WHERE email_id=?", boom) == boom_sightings
    # counted failed, reason recorded: exception class, never its message
    (problem,) = [p for p in summary["problems"] if p["email_id"] == boom]
    assert problem["outcome"] == "failed" and "RuntimeError" in problem["reason"]
    assert "secret-detail" not in repr(summary)
    assert not conn.in_transaction
