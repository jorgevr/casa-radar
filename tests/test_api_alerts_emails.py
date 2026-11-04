"""Stored-email endpoints (T045, contracts/api.md "Runs and emails").

  GET  /api/alerts/emails?outcome=failed|rejected|imported   stored emails, list without raw
  GET  /api/alerts/emails/{id}/raw                           the stored message, for inspection
  POST /api/alerts/reprocess  {"scope": "failed" | "all"}    response = run summary

The contract does not name the item fields, the content type or the error statuses; these tests read them
from data-model (`alert_emails` columns) and the task brief: item keys email_id, alert_date, subject, reason,
outcome, reader_version; an unknown outcome or scope is a 400; the raw message is served as received with a
type a browser will not render (never text/html: the stored body is the portal's HTML). Counts are by hand:
seeded = OLD_2021 (rejected), one truncated drop (failed), one new-listing fixture (imported).
"""
import base64
import sqlite3
from urllib.parse import quote

import pytest
from fastapi.testclient import TestClient

from app import zones
from app.main import create_app
from app.providers import idealista_alert as reader

from .conftest import EXAMPLE_NEEDS
from .reprocess_support import (DROP_NAME, NEW_NAME, NEW_VERSION, OLD_2021_NAME, fixture, newer_reader, truncated)

BROKEN_ID = "<broken-1@example.invalid>"
ITEM_KEYS = {"email_id", "alert_date", "subject", "reason", "outcome", "reader_version"}
SAFE_TYPES = {"message/rfc822", "text/plain", "application/octet-stream"}


@pytest.fixture(autouse=True)
def no_aliases(tmp_path, monkeypatch):
    monkeypatch.setattr(zones, "ALIASES_PATH", tmp_path / "zone_aliases.yaml")


@pytest.fixture
def client(tmp_path):
    needs = tmp_path / "needs.yaml"
    needs.write_text(EXAMPLE_NEEDS.read_text(encoding="utf-8"), encoding="utf-8")
    # context manager so the portal's event loop exists before `no_network` is applied: list `client` first
    with TestClient(create_app(str(tmp_path / "t.db"), str(needs))) as c:
        yield c


def _post_files(client, raws):
    files = [{"name": f"m{i}.eml", "content_base64": base64.b64encode(raw).decode("ascii")}
             for i, raw in enumerate(raws)]
    resp = client.post("/api/alerts/import", json={"files": files})
    assert resp.status_code == 200, resp.text
    return resp.json()


@pytest.fixture
def seeded(client):
    full = fixture(DROP_NAME)
    raws = {"broken": truncated(full, "broken-1"), "good": fixture(NEW_NAME), "old": fixture(OLD_2021_NAME)}
    summary = _post_files(client, list(raws.values()))
    assert (summary["n_found"], summary["n_imported"], summary["n_rejected"], summary["n_failed"]) == (3, 1, 1, 1)
    return {"full": full, **raws}


def _list(client, outcome):
    resp = client.get("/api/alerts/emails", params={"outcome": outcome})
    assert resp.status_code == 200, resp.text
    return resp.json()


def _db(tmp_path, sql):
    c = sqlite3.connect(str(tmp_path / "t.db"))
    try:
        return c.execute(sql).fetchall()
    finally:
        c.close()


# -- GET /api/alerts/emails ---------------------------------------------------------------------------
def test_list_filters_by_outcome(client, seeded, no_network):
    failed = _list(client, "failed")
    assert [i["email_id"] for i in failed] == [BROKEN_ID]
    item = failed[0]
    assert set(item) == ITEM_KEYS  # in particular no raw, no content
    assert item["outcome"] == "failed"
    assert item["alert_date"].startswith("2026-10-26")  # Date: Mon, 26 Oct 2026 of the drop fixture
    assert item["subject"].startswith("¡Bajada de precio")
    assert "0 tarjetas" in item["reason"]  # what was found (US4-2)
    assert item["reader_version"] == reader.READER_VERSION

    rejected = _list(client, "rejected")
    assert len(rejected) == 1 and set(rejected[0]) == ITEM_KEYS
    assert rejected[0]["alert_date"].startswith("2021-03-10")
    assert rejected[0]["reason"] == "tipo de alerta no soportado"
    assert rejected[0]["outcome"] == "rejected"

    imported = _list(client, "imported")
    assert len(imported) == 1 and set(imported[0]) == ITEM_KEYS
    assert imported[0]["alert_date"].startswith("2026-10-27")
    assert imported[0]["reason"] is None and imported[0]["outcome"] == "imported"


def test_list_never_contains_the_raw_body(client, seeded, no_network):
    for outcome in ("failed", "rejected", "imported"):
        resp = client.get("/api/alerts/emails", params={"outcome": outcome})
        assert resp.status_code == 200, resp.text
        assert all("raw" not in item for item in resp.json())
        assert "inicio inmueble" not in resp.text and "<html" not in resp.text.lower()
        assert "Content-Transfer-Encoding" not in resp.text


def test_list_with_nothing_stored_is_an_empty_list(client, no_network):
    assert _list(client, "failed") == []


def test_unknown_outcome_is_a_400(client, seeded, no_network):
    for bad in ("bogus", "already", ""):
        resp = client.get("/api/alerts/emails", params={"outcome": bad})
        assert resp.status_code == 400, (bad, resp.text)
    assert client.get("/api/alerts/emails", params={"outcome": "failed"}).status_code == 200  # route exists


def test_list_is_read_only(client, seeded, tmp_path, no_network):
    before = _db(tmp_path, "SELECT email_id, outcome, reader_version, last_run_id FROM alert_emails ORDER BY email_id")
    runs = _db(tmp_path, "SELECT COUNT(*) FROM import_runs")

    first = _list(client, "failed")
    second = _list(client, "failed")

    assert first == second and first
    assert _db(tmp_path, "SELECT email_id, outcome, reader_version, last_run_id FROM alert_emails ORDER BY email_id") == before
    assert _db(tmp_path, "SELECT COUNT(*) FROM import_runs") == runs


# -- GET /api/alerts/emails/{id}/raw ------------------------------------------------------------------
def test_raw_returns_the_stored_bytes_as_stored(client, seeded, no_network):
    resp = client.get(f"/api/alerts/emails/{quote(BROKEN_ID, safe='')}/raw")

    assert resp.status_code == 200, resp.text
    assert resp.content == seeded["broken"]  # byte for byte, nothing re-encoded or sanitised
    media_type = resp.headers["content-type"].split(";")[0].strip().lower()
    assert media_type in SAFE_TYPES  # never text/html: the stored body must not run in the app's origin


def test_raw_of_an_email_without_message_id_uses_the_hash_id(client, no_network):
    import re
    raw = re.sub(rb"(?im)^Message-ID:[^\r\n]*\r?\n", b"", fixture(OLD_2021_NAME), count=1)
    assert b"Message-ID" not in raw
    _post_files(client, [raw])
    rows = client.get("/api/alerts/emails", params={"outcome": "rejected"}).json()
    assert len(rows) == 1 and rows[0]["email_id"].startswith("sha256:")

    resp = client.get(f"/api/alerts/emails/{quote(rows[0]['email_id'], safe='')}/raw")

    assert resp.status_code == 200 and resp.content == raw


def test_raw_unknown_id_is_404(client, seeded, no_network):
    ok = client.get(f"/api/alerts/emails/{quote(BROKEN_ID, safe='')}/raw")
    assert ok.status_code == 200  # the route exists, so the next 404 is "no such email"

    missing = client.get(f"/api/alerts/emails/{quote('<nope@example.invalid>', safe='')}/raw")
    assert missing.status_code == 404
    assert client.get("/api/alerts/emails/sha256:0000/raw").status_code == 404


def test_raw_endpoint_is_read_only(client, seeded, tmp_path, no_network):
    before = _db(tmp_path, "SELECT email_id, content_hash, last_run_id FROM alert_emails ORDER BY email_id")

    assert client.get(f"/api/alerts/emails/{quote(BROKEN_ID, safe='')}/raw").status_code == 200

    assert _db(tmp_path, "SELECT email_id, content_hash, last_run_id FROM alert_emails ORDER BY email_id") == before


# -- POST /api/alerts/reprocess -----------------------------------------------------------------------
def test_reprocess_failed_returns_a_run_summary_and_imports(client, seeded, monkeypatch, tmp_path, no_network):
    newer_reader(monkeypatch, understands={BROKEN_ID: seeded["full"]})

    resp = client.post("/api/alerts/reprocess", json={"scope": "failed"})

    assert resp.status_code == 200, resp.text
    summary = resp.json()
    assert isinstance(summary["run_id"], int) and summary["kind"] == "reprocess" and summary["status"] == "ok"
    # by hand: the failed email and the rejected 2021 one are older than the new reader; the imported one is not
    assert (summary["n_found"], summary["n_imported"], summary["n_already"], summary["n_rejected"],
            summary["n_failed"]) == (2, 1, 0, 1, 0)
    assert isinstance(summary["problems"], list) and isinstance(summary["notices"], list)
    assert [p["outcome"] for p in summary["problems"]] == ["rejected"]
    assert _list(client, "failed") == []
    imported = {i["email_id"]: i for i in _list(client, "imported")}
    assert imported[BROKEN_ID]["reader_version"] == NEW_VERSION and imported[BROKEN_ID]["reason"] is None
    assert len(imported) == 2
    raw = client.get(f"/api/alerts/emails/{quote(BROKEN_ID, safe='')}/raw")
    assert raw.content == seeded["broken"]  # the original stays as received
    assert _db(tmp_path, "SELECT price FROM listings WHERE id='idealista:112842548'") == [(645000,)]
    assert _db(tmp_path, "SELECT COUNT(*) FROM import_runs WHERE kind='reprocess'") == [(1,)]


def test_reprocess_all_rereads_everything(client, seeded, monkeypatch, no_network):
    newer_reader(monkeypatch)  # new version; the truncated card is still unreadable

    resp = client.post("/api/alerts/reprocess", json={"scope": "all"})

    assert resp.status_code == 200, resp.text
    summary = resp.json()
    assert (summary["n_found"], summary["n_imported"], summary["n_already"], summary["n_rejected"],
            summary["n_failed"]) == (3, 1, 0, 1, 1)
    assert summary["n_imported"] + summary["n_already"] + summary["n_rejected"] + summary["n_failed"] == summary["n_found"]
    failed = _list(client, "failed")
    assert [i["email_id"] for i in failed] == [BROKEN_ID]
    assert failed[0]["reader_version"] == NEW_VERSION  # the attempt is recorded
    assert [p["outcome"] for p in summary["problems"] if p["outcome"] == "failed"] == ["failed"]


def test_reprocess_failed_with_nothing_older_finds_nothing(client, seeded, no_network):
    resp = client.post("/api/alerts/reprocess", json={"scope": "failed"})

    assert resp.status_code == 200, resp.text
    assert resp.json()["n_found"] == 0
    assert [i["email_id"] for i in _list(client, "failed")] == [BROKEN_ID]


@pytest.mark.parametrize("body", [{"scope": "everything"}, {"scope": ""}, {}, {"scope": None}, {"scope": 1}])
def test_invalid_scope_is_a_400_and_starts_no_run(client, seeded, tmp_path, no_network, body):
    runs = _db(tmp_path, "SELECT COUNT(*) FROM import_runs")

    resp = client.post("/api/alerts/reprocess", json=body)

    assert resp.status_code == 400, resp.text
    assert _db(tmp_path, "SELECT COUNT(*) FROM import_runs") == runs


def test_non_json_body_is_a_400(client, seeded, no_network):
    resp = client.post("/api/alerts/reprocess", content=b"not json", headers={"content-type": "application/json"})

    assert resp.status_code == 400


# -- secrets and network ------------------------------------------------------------------------------
def test_responses_expose_no_secret_and_need_no_network(client, seeded, monkeypatch, tmp_path, no_network):
    newer_reader(monkeypatch, understands={BROKEN_ID: seeded["full"]})
    responses = [client.get("/api/alerts/emails", params={"outcome": o}) for o in ("failed", "rejected", "imported")]
    responses.append(client.post("/api/alerts/reprocess", json={"scope": "all"}))

    assert [r.status_code for r in responses] == [200, 200, 200, 200]  # a 404 body would prove nothing
    for text in (r.text for r in responses):  # no_network would have raised on any connection
        lowered = text.lower()
        for word in ("client_secret", "refresh_token", "access_token", "bearer ", "password"):
            assert word not in lowered
        assert str(tmp_path / "appdata").lower() not in lowered
