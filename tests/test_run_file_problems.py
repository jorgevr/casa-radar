"""File-level problems stored with the run (follow-up to T018/T020; T017 review, non-blocking finding).

A whole-file failure (unsupported extension, unreadable or missing path, .mbox without messages) is one
found and one failed item. It has no row in alert_emails, so GET /api/runs/{id} could not list it. Decision:
it is stored with the run and returned in `problems` (outcome "failed", email_id = file name, alert_date and
subject null, a non-empty reason), never in `notices`. The JSON shape inside import_runs.notes is not asserted.

Expected values come from the task text and contracts/api.md, calculated by hand: one .msg alone gives
found/imported/already/rejected/failed = 1/0/0/0/1; a valid fixture plus a .msg gives 2/1/0/0/1; the 2021
fixture (rejected) plus a .msg gives 2/0/0/1/1.
"""
import base64
import io
import sys
from email import policy
from email.parser import BytesParser

import pytest
from fastapi.testclient import TestClient

from app import alerts, cli, db, zones
from app.main import create_app

from .conftest import EMAILS, EXAMPLE_NEEDS

OK_A = "2026-10-22_nueva-obra-nueva_obra-nueva-en-tu-zona-personalizada_112882173.eml"
OK_PRICE_DROP = "2026-10-23_bajada-de-precio_viviendas-en-tu-zona-personalizada_112692121.eml"
OLD_2021 = "2021-03-10_nuevo-piso_viviendas-tu-zona-personalizada_93231141.eml"


@pytest.fixture(autouse=True)
def no_aliases(tmp_path, monkeypatch):
    monkeypatch.setattr(zones, "ALIASES_PATH", tmp_path / "zone_aliases.yaml")


@pytest.fixture
def client(tmp_path):
    needs = tmp_path / "needs.yaml"
    needs.write_text(EXAMPLE_NEEDS.read_text(encoding="utf-8"), encoding="utf-8")
    # list `client` before `no_network` in test arguments (see T017-tests.md)
    with TestClient(create_app(str(tmp_path / "t.db"), str(needs))) as c:
        yield c


def _fixture_file(name):
    return name, (EMAILS / name).read_bytes()


def _post(client, files):
    """files: list of (name, bytes)."""
    body = {"files": [{"name": n, "content_base64": base64.b64encode(b).decode("ascii")} for n, b in files]}
    resp = client.post("/api/alerts/import", json=body)
    assert resp.status_code == 200, resp.text
    return resp.json()


def _stored(client, run_id):
    resp = client.get(f"/api/runs/{run_id}")
    assert resp.status_code == 200, resp.text
    return resp.json()


def _counts(run):
    return tuple(run[k] for k in ("n_found", "n_imported", "n_already", "n_rejected", "n_failed"))


def _assert_file_failure(run, name):
    found = [p for p in run["problems"] if p["email_id"] == name]
    assert len(found) == 1, run["problems"]
    p = found[0]
    assert p["outcome"] == "failed"
    assert p["email_id"] == name
    assert isinstance(p["reason"], str) and p["reason"].strip()
    assert p["alert_date"] is None and p["subject"] is None
    assert all(n["email_id"] != name for n in run["notices"]), run["notices"]


# (a)/(b) one file, each kind of whole-file failure, stored with the run
@pytest.mark.parametrize("name, body", [
    ("alerta.msg", b"anything at all"),
    ("vacio.mbox", b""),
    # a bare .eml saved with an .mbox name is not valid mbox (no "From " separator line)
    ("guardado.mbox", (EMAILS / OK_A).read_bytes()),
], ids=["unsupported-msg", "empty-mbox", "eml-saved-as-mbox"])
def test_file_failure_is_stored_and_listed_in_run_detail(client, no_network, name, body):
    run_id = _post(client, [(name, body)])["run_id"]

    run = _stored(client, run_id)

    assert _counts(run) == (1, 0, 0, 0, 1)
    assert len(run["problems"]) == 1
    _assert_file_failure(run, name)
    assert run["notices"] == []

    listed = [r for r in client.get("/api/runs").json() if r["run_id"] == run_id]
    assert len(listed) == 1
    assert _counts(listed[0]) == (1, 0, 0, 0, 1)
    assert len(listed[0]["problems"]) == 1
    _assert_file_failure(listed[0], name)
    assert listed[0]["notices"] == []


# (c) mixed run: valid fixture + .msg
def test_mixed_run_counts_add_up_and_failure_listed_once(client, no_network):
    posted = _post(client, [_fixture_file(OK_A), ("alerta.msg", b"x")])

    # 2 found = 1 imported + 1 failed
    assert _counts(posted) == (2, 1, 0, 0, 1)
    assert len(posted["problems"]) == 1  # exactly once in the POST response
    _assert_file_failure(posted, "alerta.msg")

    stored = _stored(client, posted["run_id"])
    assert _counts(stored) == (2, 1, 0, 0, 1)
    assert len(stored["problems"]) == 1
    _assert_file_failure(stored, "alerta.msg")


# (d) rejected email (alert_emails) + file failure
def test_rejected_email_and_file_failure_are_both_stored(client, no_network):
    posted = _post(client, [_fixture_file(OLD_2021), ("alerta.msg", b"x")])
    assert _counts(posted) == (2, 0, 0, 1, 1)

    stored = _stored(client, posted["run_id"])

    assert _counts(stored) == (2, 0, 0, 1, 1)
    assert len(stored["problems"]) == 2
    assert sorted(p["outcome"] for p in stored["problems"]) == ["failed", "rejected"]
    rejected = next(p for p in stored["problems"] if p["outcome"] == "rejected")
    assert rejected["alert_date"].startswith("2021-03-10")
    _assert_file_failure(stored, "alerta.msg")


# (e) import_paths called directly on a missing path
def test_import_paths_missing_path_listed_once_and_readable_later(client, tmp_path, no_network):
    # the client's app owns t.db; import_paths gets its own connection to the same file
    conn = db.connect(str(tmp_path / "t.db"))
    try:
        summary = alerts.import_paths(conn, [tmp_path / "no-existe.eml"], kind="file_cli")
    finally:
        conn.close()

    assert _counts(summary) == (1, 0, 0, 0, 1)
    assert len(summary["problems"]) == 1
    _assert_file_failure(summary, "no-existe.eml")

    stored = _stored(client, summary["run_id"])
    assert stored["kind"] == "file_cli"
    assert _counts(stored) == (1, 0, 0, 0, 1)
    assert len(stored["problems"]) == 1
    _assert_file_failure(stored, "no-existe.eml")


# (f) notices keep working and stay separate from file failures
def _eml_with_notice():
    """The 23 Oct price-drop fixture with an extra attribute token, built in memory as in T008
    (no fixture yields a notice by itself): the reader reports 'atributo no reconocido: "2 baños"'."""
    msg = BytesParser(policy=policy.default).parsebytes((EMAILS / OK_PRICE_DROP).read_bytes())
    part = next(p for p in msg.walk() if p.get_content_type() == "text/html")
    html = part.get_content()
    assert "6 hab." in html
    part.set_content(html.replace("6 hab.", "6 hab.     2 baños", 1), subtype="html")
    return bytes(msg)


def test_notices_are_unchanged_by_file_failures(client, no_network):
    posted = _post(client, [("con-aviso.eml", _eml_with_notice()), ("alerta.msg", b"x")])

    assert _counts(posted) == (2, 1, 0, 0, 1)
    assert len(posted["notices"]) == 1
    assert "2 baños" in posted["notices"][0]["text"]

    stored = _stored(client, posted["run_id"])
    assert len(stored["notices"]) == 1
    assert "2 baños" in stored["notices"][0]["text"]
    assert stored["notices"][0]["email_id"] != "alerta.msg"
    assert stored["notices"][0]["subject"] is not None  # the notice still points at its email
    assert len(stored["problems"]) == 1
    _assert_file_failure(stored, "alerta.msg")


# (g) a file failure belongs to its own run
def test_same_missing_path_twice_gives_two_runs_each_with_its_own_failure(client, tmp_path, no_network):
    conn = db.connect(str(tmp_path / "t.db"))
    try:
        first = alerts.import_paths(conn, [tmp_path / "no-existe.eml"])
        second = alerts.import_paths(conn, [tmp_path / "no-existe.eml"])
    finally:
        conn.close()
    assert first["run_id"] != second["run_id"]

    for summary in (first, second):
        stored = _stored(client, summary["run_id"])
        assert _counts(stored) == (1, 0, 0, 0, 1)
        assert len(stored["problems"]) == 1  # not 2: nothing leaks from the other run
        _assert_file_failure(stored, "no-existe.eml")

    # and a later run without a file failure shows none
    clean = _post(client, [_fixture_file(OK_A)])
    assert _stored(client, clean["run_id"])["problems"] == []


# CLI: one FALLO line per file failure, once
def test_cli_summary_prints_one_fallo_line_per_file_failure(tmp_path, monkeypatch, no_network):
    bad = tmp_path / "alerta.msg"
    bad.write_bytes(b"x")
    out = io.TextIOWrapper(io.BytesIO(), encoding="utf-8", errors="strict", newline="")
    monkeypatch.setattr(sys, "stdout", out)

    code = cli.main(["import-emails", str(bad), str(tmp_path / "no-existe.eml")])
    out.flush()
    text = out.buffer.getvalue().decode("utf-8")

    assert code == 1  # n_failed > 0
    lines = text.splitlines()
    assert sum(1 for ln in lines if ln.startswith("FALLO") and "alerta.msg" in ln) == 1
    assert sum(1 for ln in lines if ln.startswith("FALLO") and "no-existe.eml" in ln) == 1
    assert sum(1 for ln in lines if ln.startswith("FALLO")) == 2
    assert "2 emails: 0 importados, 0 ya procesados, 0 rechazados, 2 fallidos" in text
