"""T064 - Article VIII end to end: ranking is reproducible and carries its scoring version.

Same db + same needs -> byte-identical ranking, twice, through the real API path; `scoring_version`
is on every /api/listings item and is a column of /api/export.csv (contracts/api.md, "Changes to
existing endpoints"). The expected version is research R14's literal (2), not read from app code.
"""
import base64
import csv
import io

import pytest
from fastapi.testclient import TestClient

from app import zones
from app.main import create_app

from .conftest import EMAILS, EXAMPLE_NEEDS

FILES = [
    "2026-10-22_nueva-obra-nueva_obra-nueva-en-tu-zona-personalizada_112882173.eml",
    "2026-10-23_nuevo-chalet-independiente_viviendas-en-tu-zona-personalizada_112887282.eml",
    "2026-10-23_bajada-de-precio_viviendas-en-tu-zona-personalizada_112658090.eml",
    "2026-10-26_bajada-de-precio_chalets-en-tu-zona-personalizada_112842548.eml",
]


@pytest.fixture(autouse=True)
def no_aliases(tmp_path, monkeypatch):
    monkeypatch.setattr(zones, "ALIASES_PATH", tmp_path / "zone_aliases.yaml")


@pytest.fixture
def imported(tmp_path):
    needs = tmp_path / "needs.yaml"
    needs.write_text(EXAMPLE_NEEDS.read_text(encoding="utf-8"), encoding="utf-8")
    with TestClient(create_app(str(tmp_path / "t.db"), str(needs))) as c:
        body = {"files": [{"name": n, "content_base64": base64.b64encode((EMAILS / n).read_bytes()).decode("ascii")}
                          for n in FILES]}
        resp = c.post("/api/alerts/import", json=body)
        assert resp.status_code == 200, resp.text
        assert resp.json()["n_imported"] == len(FILES)
        yield c


def test_ranking_twice_is_identical(imported, no_network):
    first = imported.get("/api/listings")
    second = imported.get("/api/listings")

    assert first.status_code == second.status_code == 200
    assert len(first.json()) == len(FILES)
    assert first.json() == second.json()
    assert first.text == second.text  # byte for byte, key order included


def test_csv_export_twice_is_identical(imported, no_network):
    assert imported.get("/api/export.csv").text == imported.get("/api/export.csv").text


def test_scoring_version_on_every_listing_and_csv_row(imported, no_network):
    listings = imported.get("/api/listings").json()
    assert [l.get("scoring_version") for l in listings] == [2] * len(FILES)

    rows = list(csv.reader(io.StringIO(imported.get("/api/export.csv").text)))
    header, body = rows[0], rows[1:]
    assert "scoring_version" in header
    assert [r[header.index("scoring_version")] for r in body] == ["2"] * len(FILES)
