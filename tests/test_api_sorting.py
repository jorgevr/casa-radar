"""Published and updated dates in the API and the CSV export (T025, US2, FR-036; code is T028/T029).

Expected values are read by hand from the fixtures' Date headers (the alert's own local date) and from
the alert type of each email, never from the code's output:

- 112882173  "Nueva obra nueva" (new listing), Date: Thu, 22 Oct 2026 19:01:18 +0200
             -> published_at 2026-10-22, no price change -> price_updated_at null
- 112887282  new listing,                      Date: Fri, 23 Oct 2026 07:04:00 +0200
             -> published_at 2026-10-23, price_updated_at null
- 112658090  price drop (Tres Cantos),         Date: Fri, 23 Oct 2026 21:35:58 +0200
             -> published_at null (never seen in a new-listing alert, FR-036), price_updated_at 2026-10-23
- 112842548  price drop (Torrejon),            Date: Mon, 26 Oct 2026 12:28:28 +0100
             -> published_at null, price_updated_at 2026-10-26 (tasks.md, Phase 4 Independent Test)
"""
import base64
import csv
import io

import pytest
from fastapi.testclient import TestClient

from app import zones
from app.main import create_app

from .conftest import EMAILS, EXAMPLE_NEEDS

NEW_OBRA = "2026-10-22_nueva-obra-nueva_obra-nueva-en-tu-zona-personalizada_112882173.eml"
NEW_CHALET = "2026-10-23_nuevo-chalet-independiente_viviendas-en-tu-zona-personalizada_112887282.eml"
DROP_TRES_CANTOS = "2026-10-23_bajada-de-precio_viviendas-en-tu-zona-personalizada_112658090.eml"
DROP_TORREJON = "2026-10-26_bajada-de-precio_chalets-en-tu-zona-personalizada_112842548.eml"
FILES = [NEW_OBRA, NEW_CHALET, DROP_TRES_CANTOS, DROP_TORREJON]

# code -> (published_at, price_updated_at); None = unknown / no price change seen
EXPECTED = {
    "112882173": ("2026-10-22", None),
    "112887282": ("2026-10-23", None),
    "112658090": (None, "2026-10-23"),
    "112842548": (None, "2026-10-26"),
}


@pytest.fixture(autouse=True)
def no_aliases(tmp_path, monkeypatch):
    monkeypatch.setattr(zones, "ALIASES_PATH", tmp_path / "zone_aliases.yaml")


@pytest.fixture
def client(tmp_path):
    needs = tmp_path / "needs.yaml"
    needs.write_text(EXAMPLE_NEEDS.read_text(encoding="utf-8"), encoding="utf-8")
    # context manager first, `no_network` after (see tests/test_api_alerts.py)
    with TestClient(create_app(str(tmp_path / "t.db"), str(needs))) as c:
        yield c


@pytest.fixture
def imported(client):
    body = {"files": [{"name": n, "content_base64": base64.b64encode((EMAILS / n).read_bytes()).decode("ascii")}
                      for n in FILES]}
    resp = client.post("/api/alerts/import", json=body)
    assert resp.status_code == 200, resp.text
    assert resp.json()["n_imported"] == len(FILES)
    return client


def test_listings_return_published_and_updated_dates(imported, no_network):
    resp = imported.get("/api/listings")

    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert isinstance(data, list)  # still a plain list; the per-listing scoring_version is T032 (Phase 5)
    by_id = {l["id"]: l for l in data}
    assert set(by_id) == {f"idealista:{c}" for c in EXPECTED}
    for code, (published, updated) in EXPECTED.items():
        listing = by_id[f"idealista:{code}"]
        assert "published_at" in listing and "price_updated_at" in listing, code
        assert listing["published_at"] == published, code
        assert listing["price_updated_at"] == updated, code


def _rows(client):
    resp = client.get("/api/export.csv")
    assert resp.status_code == 200, resp.text
    rows = list(csv.reader(io.StringIO(resp.text)))
    return rows[0], rows[1:]


def test_export_csv_has_the_new_columns(imported, no_network):
    header, rows = _rows(imported)

    for col in ("published_at", "price_updated_at", "found_via", "scoring_version"):
        assert col in header, col
    assert len(rows) == len(FILES)
    assert all(len(r) == len(header) for r in rows)


def test_export_csv_scoring_version_and_found_via(imported, no_network):
    header, rows = _rows(imported)
    sv, fv = header.index("scoring_version"), header.index("found_via")

    # research R14: SCORING_VERSION = 2 (the literal is intentional; it is not imported from app)
    assert [r[sv] for r in rows] == ["2"] * len(FILES)
    # Phase 4: no category data yet, so found_via is empty = unknown (Article I).
    # THIS ASSERTION CHANGES IN PHASE 5 (T034 wires categories and found_via gets values).
    assert [r[fv] for r in rows] == [""] * len(FILES)


def test_export_csv_dates_match_the_listings_and_null_is_empty(imported, no_network):
    header, rows = _rows(imported)
    url, pub, upd = header.index("url"), header.index("published_at"), header.index("price_updated_at")

    for code, (published, updated) in EXPECTED.items():
        matching = [r for r in rows if f"/{code}/" in r[url]]  # the listing's direct link holds its code
        assert len(matching) == 1, code
        assert matching[0][pub] == (published or ""), code
        assert matching[0][upd] == (updated or ""), code
