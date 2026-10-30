"""HTTP API for file import of alert emails and import runs (T017, US3; endpoints are T020).

Expected numbers come from the task text and contracts/api.md, calculated by hand: two importable
fixtures give found/imported/already/rejected/failed = 2/2/0/0/0, then 2/0/2/0/0 on a second post; the
2021 fixture is the one email that must be rejected (1/0/0/1/0).
"""
import base64
import sqlite3

import pytest
from fastapi.testclient import TestClient

from app import zones
from app.main import create_app

from .conftest import EMAILS, EXAMPLE_NEEDS

OK_A = "2026-10-22_nueva-obra-nueva_obra-nueva-en-tu-zona-personalizada_112882173.eml"
OK_B = "2026-10-23_bajada-de-precio_viviendas-en-tu-zona-personalizada_112658090.eml"
OLD_2021 = "2021-03-10_nuevo-piso_viviendas-tu-zona-personalizada_93231141.eml"


@pytest.fixture(autouse=True)
def no_aliases(tmp_path, monkeypatch):
    monkeypatch.setattr(zones, "ALIASES_PATH", tmp_path / "zone_aliases.yaml")


@pytest.fixture
def client(tmp_path):
    needs = tmp_path / "needs.yaml"
    needs.write_text(EXAMPLE_NEEDS.read_text(encoding="utf-8"), encoding="utf-8")
    # Entered as a context manager so the portal's event loop (whose self-pipe socketpair needs a local
    # socket.connect on Windows) exists before `no_network` is applied: list `client` before `no_network`.
    with TestClient(create_app(str(tmp_path / "t.db"), str(needs))) as c:
        yield c


def _file(name):
    return {"name": name, "content_base64": base64.b64encode((EMAILS / name).read_bytes()).decode("ascii")}


def _post(client, names):
    return client.post("/api/alerts/import", json={"files": [_file(n) for n in names]})


def _import(client, names):
    resp = _post(client, names)
    assert resp.status_code == 200, resp.text
    return resp.json()


def _count(tmp_path, table):
    c = sqlite3.connect(str(tmp_path / "t.db"))
    try:
        return c.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    finally:
        c.close()


def _counts(summary):
    return tuple(summary[k] for k in ("n_found", "n_imported", "n_already", "n_rejected", "n_failed"))


def test_api_import(client, tmp_path, no_network):
    resp = _post(client, [OK_A, OK_B])

    assert resp.status_code == 200, resp.text
    first = resp.json()
    assert _counts(first) == (2, 2, 0, 0, 0)
    assert isinstance(first["run_id"], int)
    assert first["problems"] == []
    assert isinstance(first["notices"], list)
    assert first["n_new_listings"] == 2
    assert _count(tmp_path, "listings") == 2
    assert _count(tmp_path, "alert_emails") == 2

    # same two files again: both already processed, nothing new
    again = _post(client, [OK_A, OK_B])
    assert again.status_code == 200, again.text
    second = again.json()
    assert _counts(second) == (2, 0, 2, 0, 0)
    assert second["run_id"] > first["run_id"]
    assert second["n_new_listings"] == 0
    assert _count(tmp_path, "listings") == 2
    assert _count(tmp_path, "alert_emails") == 2


def test_api_import_rejected_email_is_a_problem_not_an_error(client, no_network):
    resp = _post(client, [OLD_2021])

    assert resp.status_code == 200, resp.text  # 400 only for a malformed request
    body = resp.json()
    assert _counts(body) == (1, 0, 0, 1, 0)
    assert len(body["problems"]) == 1
    assert body["problems"][0]["outcome"] == "rejected"
    assert body["problems"][0]["alert_date"].startswith("2021-03-10")


def test_api_import_run_kind_is_file_ui(client, no_network):
    # data-model import_runs.kind: a file import from the UI is `file_ui`
    run_id = _import(client, [OK_A])["run_id"]

    run = client.get(f"/api/runs/{run_id}")

    assert run.status_code == 200, run.text
    assert run.json()["kind"] == "file_ui"


@pytest.mark.parametrize("body", [
    {},
    {"files": "a.eml"},
    {"files": {"name": "a.eml"}},
    {"files": [{"name": "a.eml"}]},
    {"files": [{"content_base64": "AAAA"}]},
    {"files": [{"name": "a.eml", "content_base64": "%%% not base64 %%%"}]},
    {"files": ["a.eml"]},
    {"files": [{"name": "a.eml", "content_base64": 123}]},
], ids=["no-files", "files-string", "files-object", "no-content", "no-name", "bad-base64", "item-string", "content-int"])
def test_api_import_malformed_body_is_400(client, no_network, body):
    resp = client.post("/api/alerts/import", json=body)

    assert resp.status_code == 400, resp.text


def test_api_import_body_not_json_is_400(client, no_network):
    resp = client.post("/api/alerts/import", content=b"not json", headers={"Content-Type": "application/json"})

    assert resp.status_code == 400, resp.text


def test_api_import_malformed_creates_no_run(client, tmp_path, no_network):
    resp = client.post("/api/alerts/import", json={"files": [{"name": "a.eml"}]})

    assert resp.status_code == 400, resp.text
    assert _count(tmp_path, "import_runs") == 0
    assert _count(tmp_path, "alert_emails") == 0


def test_api_runs_list_newest_first_and_limit(client, no_network):
    ids = [_import(client, [OK_A])["run_id"],
           _import(client, [OK_A])["run_id"],
           _import(client, [OK_B])["run_id"]]
    assert ids == sorted(ids) and len(set(ids)) == 3  # run_id is increasing (data-model)

    resp = client.get("/api/runs")

    assert resp.status_code == 200, resp.text
    runs = resp.json()
    assert [r["run_id"] for r in runs] == sorted(ids, reverse=True)
    newest = runs[0]
    assert _counts(newest) == (1, 1, 0, 0, 0)  # the third post: OK_B, new
    assert _counts(runs[1]) == (1, 0, 1, 0, 0)  # the second post: OK_A again
    assert _counts(runs[2]) == (1, 1, 0, 0, 0)  # the first post: OK_A, new

    limited = client.get("/api/runs?limit=2")
    assert limited.status_code == 200, limited.text
    assert [r["run_id"] for r in limited.json()] == [ids[2], ids[1]]


def test_api_runs_get_one_with_problems(client, no_network):
    run_id = _import(client, [OK_A, OLD_2021])["run_id"]

    resp = client.get(f"/api/runs/{run_id}")

    assert resp.status_code == 200, resp.text
    run = resp.json()
    assert run["run_id"] == run_id
    assert _counts(run) == (2, 1, 0, 1, 0)
    assert len(run["problems"]) == 1
    problem = run["problems"][0]
    assert problem["outcome"] == "rejected"
    assert problem["alert_date"].startswith("2021-03-10")
    assert isinstance(run["notices"], list)


def test_api_runs_unknown_id_is_404(client, no_network):
    real = _import(client, [OK_A])["run_id"]
    assert client.get(f"/api/runs/{real}").status_code == 200

    resp = client.get(f"/api/runs/{real + 1000}")

    assert resp.status_code == 404, resp.text
