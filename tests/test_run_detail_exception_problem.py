"""A reprocess exception shown in GET /api/runs/{id} carries the email's date and subject (like other problems).

Whole-file failures (no alert_emails row, email_id = file name) keep date and subject null.
"""
import base64

import pytest
from fastapi.testclient import TestClient

from app import zones
from app.main import create_app
from app.providers import idealista_alert as reader

from .conftest import EXAMPLE_NEEDS
from .reprocess_support import DROP_NAME, fixture, message_id


@pytest.fixture(autouse=True)
def no_aliases(tmp_path, monkeypatch):
    monkeypatch.setattr(zones, "ALIASES_PATH", tmp_path / "zone_aliases.yaml")


@pytest.fixture
def client(tmp_path):
    needs = tmp_path / "needs.yaml"
    needs.write_text(EXAMPLE_NEEDS.read_text(encoding="utf-8"), encoding="utf-8")
    with TestClient(create_app(str(tmp_path / "t.db"), str(needs))) as c:
        yield c


def test_exception_problem_in_run_detail_has_date_and_subject(client, monkeypatch, no_network):
    raw = fixture(DROP_NAME)
    files = [{"name": "m.eml", "content_base64": base64.b64encode(raw).decode("ascii")}]
    assert client.post("/api/alerts/import", json={"files": files}).json()["n_imported"] == 1
    email_id = message_id(raw)

    original = reader.read

    def boom(msg):
        if str(msg["Message-ID"]) == email_id:
            raise RuntimeError("detail-that-must-not-appear")
        return original(msg)

    monkeypatch.setattr(reader, "read", boom)
    summary = client.post("/api/alerts/reprocess", json={"scope": "all"}).json()
    (live,) = summary["problems"]
    assert live["alert_date"] and live["subject"]  # precondition: the live summary already has them

    detail = client.get(f"/api/runs/{summary['run_id']}").json()
    (problem,) = detail["problems"]
    assert problem["email_id"] == email_id and problem["outcome"] == "failed"
    assert "RuntimeError" in problem["reason"] and "detail-that-must-not-appear" not in repr(detail)
    assert problem["alert_date"] == live["alert_date"]
    assert problem["subject"] == live["subject"]


def test_whole_file_failure_keeps_null_date_and_subject(client, no_network):
    files = [{"name": "notes.txt", "content_base64": base64.b64encode(b"hello").decode("ascii")}]
    summary = client.post("/api/alerts/import", json={"files": files}).json()
    detail = client.get(f"/api/runs/{summary['run_id']}").json()
    (problem,) = detail["problems"]
    assert problem["email_id"] == "notes.txt"
    assert problem["alert_date"] is None and problem["subject"] is None
