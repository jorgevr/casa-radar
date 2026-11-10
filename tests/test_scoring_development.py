"""T039 - golden test for developments (FR-034, research R13 and R15, Article VII; code is T040/T041).

Rules under test:
- R13: a listing with development=1 keeps its stated price but the scorer treats it as having no unit price:
  price, affordability and momentum components are None, flag "promoción: sin vivienda elegida" (data-model
  flag table), max_price / min_area_m2 / min_bedrooms flag instead of excluding, no duplicate check.
- After PATCH /api/listings/{id} with unit price, area and bedrooms (origin manual) it is scored like any
  listing, and R15 applies: |a-b|/max(a,b) <= 0.03 area and <= 0.05 price (inclusive), same zone, type, bedrooms.

Needs used (config/needs.example.yaml plus the overrides in NEEDS_OVERRIDES below):
  savings 200000, net income 4000/month, tin 3.0 %, 30 years, max_effort 0.35, itp 0.06, other_pct 0.012,
  max_ltv 0.80, max_price 500000.

Hand calculation of the affordability component for the chosen unit (price 450000, second-hand, because
new_build is unknown/null and unknown is never imputed as new, Article I):
  taxes        = 450000 * 0.06  = 27000          (itp, needs.example.yaml `costs`)
  other costs  = 450000 * 0.012 =  5400          (other_pct)
  upfront costs = 27000 + 5400  = 32400
  down payment = 200000 - 32400 = 167600         (savings pay costs first, then the down payment)
  loan         = 450000 - 167600 = 282400        (LTV 62.8 % <= 80 %, so no savings shortfall;
                                                  minimum savings 450000*0.20 + 32400 = 122400 <= 200000)
  monthly payment, French amortisation (standard annuity formula, e.g. Banco de Espana mortgage guide):
    P = L * i / (1 - (1+i)^-n), i = 0.03/12 = 0.0025, n = 360
    (1.0025)^360 = 2.456842 ; 1 - 1/2.456842 = 0.592974 ; P = 282400 * 0.0025 / 0.592974 = 1190.61
    cross-check with the published factor of 421.60 EUR per 100000 EUR at 3 % / 30 years: 2.824 * 421.60 = 1190.6
  effort ratio e = 1190.61 / 4000 = 0.29765
  affordability component = clamp(1 - (e - 0.7*cap) / (0.3*cap)) with cap = 0.35 (formula as documented in
    the scoring design; 0.7*cap = 0.245, 0.3*cap = 0.105):
    1 - (0.29765 - 0.245) / 0.105 = 1 - 0.50147 = 0.4985
Duplicate check (R15) against the flat (price 440000, area 118, 4 bedrooms, same zone and type):
  area  |120 - 118| / max = 2 / 120 = 0.0167 <= 0.03
  price |450000 - 440000| / max = 10000 / 450000 = 0.0222 <= 0.05
A far-off flat (area 100, price 450000) is a trap that must NOT match: |120 - 100| / 120 = 0.1667 > 0.03.
"""
import copy

import pytest
from fastapi.testclient import TestClient

from app import db
from app.main import create_app

from .conftest import EXAMPLE_NEEDS

ZONE = "zona-a"
DEV, FLAT, FAR = "dev-1", "flat-1", "flat-far"
DEV_FLAG = "promoción: sin vivienda elegida"
NEEDS_OVERRIDES = {
    "finance": {"savings": 200_000, "net_income_monthly": 4_000, "max_price": 500_000},
    "home": {"property_types": []},  # no type filter: developments have no mapped type (data-model)
}


@pytest.fixture
def client(tmp_path):
    needs = tmp_path / "needs.yaml"
    needs.write_text(EXAMPLE_NEEDS.read_text(encoding="utf-8"), encoding="utf-8")
    path = str(tmp_path / "t.db")
    with TestClient(create_app(path, str(needs))) as c:
        body = copy.deepcopy(c.get("/api/needs").json())
        for section, values in NEEDS_OVERRIDES.items():
            body[section].update(values)
        assert c.put("/api/needs", json=body).status_code == 200
        c.db_path = path
        yield c


def _insert(client, lid, price, area, beds, development=0):
    c = db.connect(client.db_path)
    try:
        c.execute("INSERT OR IGNORE INTO zones(zone_id,name,municipality,level) VALUES(?,?,?,?)",
                  (ZONE, ZONE, "test", "municipality"))
        c.execute("INSERT INTO listings(id,source,url,property_type,price,area_m2,bedrooms,zone_id,development)"
                  " VALUES(?,?,?,?,?,?,?,?,?)",
                  (lid, "alert", f"https://x.test/{lid}", "piso", price, area, beds, ZONE, development))
        c.commit()
    finally:
        c.close()


def _rows(client):
    resp = client.get("/api/listings")
    assert resp.status_code == 200, resp.text
    return {r["id"]: r for r in resp.json()}


def _dups(row):
    return [f for f in row["eval"]["flags"] if "duplicado" in f]


def test_development_golden(client, no_network):
    # A development with a stated price of 600000 (above max_price 500000) and no area or bedrooms,
    # a matching flat and a far-off flat that must never match.
    _insert(client, DEV, 600_000, None, None, development=1)
    _insert(client, FLAT, 440_000, 118, 4)
    _insert(client, FAR, 450_000, 100, 4)

    # --- before the PATCH: no unit chosen ---------------------------------------------------------
    dev = _rows(client)[DEV]
    comps = dev["eval"]["components"]
    assert dev["price"] == 600_000  # stated price is kept as stated (FR-034)
    assert comps["price"] is None and comps["affordability"] is None and comps["momentum"] is None
    assert DEV_FLAG in dev["eval"]["flags"]
    # 600000 > max_price 500000 would exclude an ordinary listing; a development is flagged instead (R13)
    assert dev["eval"]["excluded"] == []
    assert _dups(dev) == []
    assert _dups(_rows(client)[FLAT]) == []  # nothing points at the development either

    # --- the user chooses a unit: price 450000, 120 m2, 4 bedrooms --------------------------------
    resp = client.patch(f"/api/listings/{DEV}", json={"price": 450_000, "area_m2": 120, "bedrooms": 4})
    assert resp.status_code == 200, resp.text

    rows = _rows(client)
    dev = rows[DEV]
    assert (dev["price"], dev["area_m2"], dev["bedrooms"]) == (450_000, 120, 4)
    sources = dev["field_sources"]
    if isinstance(sources, str):
        import json
        sources = json.loads(sources)
    assert {k: sources.get(k) for k in ("price", "area_m2", "bedrooms")} == \
        {"price": "manual", "area_m2": "manual", "bedrooms": "manual"}

    flags = dev["eval"]["flags"]
    assert DEV_FLAG not in flags  # scored like any listing now
    assert dev["eval"]["excluded"] == []  # 450000 <= 500000, 120 >= 90, 4 >= 4
    # affordability: hand calculation in the module docstring (effort 0.29765 -> component 0.4985)
    assert dev["eval"]["components"]["affordability"] == pytest.approx(0.4985, abs=2e-3)
    assert dev["eval"]["mortgage"]["loan"] == pytest.approx(282_400)
    assert dev["eval"]["mortgage"]["monthly"] == pytest.approx(1190.61, abs=0.05)
    assert dev["eval"]["score"] is not None
    assert not any("te faltan" in f for f in flags)  # savings 200000 >= minimum 122400

    # duplicate check now applies, reciprocally, and only to the flat within the R15 limits
    assert _dups(dev) == [f"posible duplicado de {FLAT}"]
    assert _dups(rows[FLAT]) == [f"posible duplicado de {DEV}"]
    assert _dups(rows[FAR]) == []
