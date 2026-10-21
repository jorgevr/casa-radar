import json
import sys
from pathlib import Path

import httpx
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from app import db, mortgage, scoring
from app.etl import indicators as ind_etl
from app.etl import madrid_ckan, overpass, serpavi
from app.listings import upsert_listing, zone_for
from app.main import create_app
from app.providers import csv_import, idealista_mcp
from app.util import to_float

NEEDS = db.load_needs(str(Path(__file__).parent.parent / "config" / "needs.yaml"))


@pytest.fixture
def conn():
    c = db.connect(":memory:")
    ind_etl.seed_madrid_districts(c)
    return c


# ── mortgage ─────────────────────────────────────────────────────────────────
def test_monthly_payment_known_value():
    assert mortgage.monthly_payment(200_000, 3.0, 30) == pytest.approx(843.21, abs=0.01)
    assert mortgage.monthly_payment(120_000, 0.0, 10) == pytest.approx(1000.0)


def test_simulate_costs_and_shortfall():
    s = mortgage.simulate(400_000, 100_000, 30, 3.0, net_income_monthly=5000)
    assert s["taxes"] == pytest.approx(24_000)           # 6% ITP
    assert s["other_costs"] == pytest.approx(4_800)      # 1.2%
    assert s["loan"] == pytest.approx(400_000 - (100_000 - 28_800))
    assert s["savings_shortfall"] == pytest.approx(8_800)  # LTV 82% > 80%: need 108.8k
    assert s["effort_ratio"] == pytest.approx(s["monthly"] / 5000)
    assert s["stress"][1]["monthly"] > s["stress"][0]["monthly"] > s["monthly"]


def test_new_build_uses_iva_plus_ajd():
    s = mortgage.simulate(300_000, 100_000, 30, 3.0, new_build=True)
    assert s["taxes"] == pytest.approx(300_000 * 0.1075)


# ── parsing / listings ───────────────────────────────────────────────────────
def test_to_float_spanish_formats():
    assert to_float("1.250.000") == 1_250_000
    assert to_float("1.250,5") == 1250.5
    assert to_float("450000 €") == 450_000
    assert to_float("") is None


def test_zone_assignment_district_level_for_madrid():
    assert zone_for("Madrid", "Chamberí", NEEDS)[0] == "madrid/chamberi"
    assert zone_for("Alcorcón", "Centro", NEEDS)[0] == "alcorcon"


def test_csv_import_and_price_history(conn):
    csv_text = ("url;title;property_type;price;area_m2;bedrooms;municipality;district;garden\n"
                "https://x.test/1;Chalet;Chalet;450.000;180;4;Alcorcón;;si\n")
    ids = csv_import.import_csv_text(conn, csv_text, NEEDS)
    assert len(ids) == 1
    row = conn.execute("SELECT * FROM listings").fetchone()
    assert (row["price"], row["zone_id"], row["garden"], row["property_type"]) == (450_000, "alcorcon", 1, "chalet")
    csv_import.import_csv_text(conn, csv_text.replace("450.000", "420.000"), NEEDS)  # same URL, lower price
    assert conn.execute("SELECT COUNT(*) FROM listings").fetchone()[0] == 1
    assert [r[0] for r in conn.execute("SELECT price FROM price_history ORDER BY rowid")] == [450_000, 420_000]


# ── scoring ──────────────────────────────────────────────────────────────────
def _listing(conn, price, zone_muni="Alcorcón", **kw):
    d = {"url": f"https://x.test/{price}{zone_muni}", "property_type": "chalet", "price": price, "area_m2": 150,
         "bedrooms": 4, "municipality": zone_muni, "garden": 1, **kw}
    return upsert_listing(conn, d, "manual", NEEDS)


def test_neighbourhood_percentiles_respect_direction():
    ind = {"a": {"income_hh": 30000, "no2": 40}, "b": {"income_hh": 20000, "no2": 20}, "c": {"income_hh": 10000, "no2": 30}}
    cfg = {"neighbourhood": {"indicators": {"income_hh": {"weight": 1, "direction": "higher"},
                                            "no2": {"weight": 1, "direction": "lower"}}}}
    s = scoring.neighbourhood_scores(ind, cfg)
    assert s["a"]["parts"]["income_hh"] == 1.0 and s["a"]["parts"]["no2"] == 0.0
    assert s["b"]["parts"]["no2"] == 1.0
    assert s["a"]["score"] == pytest.approx(0.5)


def test_single_zone_gets_no_neighbourhood_score():
    cfg = {"neighbourhood": {"indicators": {"income_hh": {"weight": 1, "direction": "higher"}}}}
    assert scoring.neighbourhood_scores({"a": {"income_hh": 1}}, cfg)["a"]["score"] is None


def test_price_vs_notary_benchmark_and_markup(conn):
    lid = _listing(conn, 450_000)  # 3000 €/m²
    ind_etl.import_csv(conn, "zone,key,value\nalcorcon,notary_price_m2_house,2500\n")
    r = {x["id"]: x for x in scoring.rank(conn, NEEDS)}[lid]["eval"]
    assert r["benchmark_source"] == "notarial" and r["discount_vs_benchmark"] == pytest.approx(-0.2)
    needs2 = json.loads(json.dumps(NEEDS)); needs2["market"]["asking_markup"] = 0.2
    r2 = {x["id"]: x for x in scoring.rank(conn, needs2)}[lid]["eval"]
    assert r2["discount_vs_benchmark"] == pytest.approx(0.0)
    assert r2["components"]["price"] > r["components"]["price"]


def test_median_fallback_flagged_and_needs_min_listings(conn):
    ids = [_listing(conn, p) for p in (300_000, 330_000, 360_000, 390_000, 420_000)]
    r = {x["id"]: x for x in scoring.rank(conn, NEEDS)}[ids[0]]["eval"]
    assert r["benchmark_source"] == "mediana de tus anuncios"
    assert any("sesgo de selección" in f for f in r["flags"])
    assert r["discount_vs_benchmark"] > 0  # cheapest vs the median
    only = _listing(conn, 500_000, zone_muni="Alcobendas")
    r2 = {x["id"]: x for x in scoring.rank(conn, NEEDS)}[only]["eval"]
    assert r2["benchmark_m2"] is None and r2["components"]["price"] is None


def test_missing_data_renormalised_and_coverage_reported(conn):
    lid = _listing(conn, 450_000)
    e = {x["id"]: x for x in scoring.rank(conn, NEEDS)}[lid]["eval"]
    assert e["score"] is not None and e["coverage"] < 0.5   # only fit/…: honest low coverage
    assert any("Necesidades" in f for f in e["flags"])


def test_affordability_flags_and_hard_filters(conn):
    needs = json.loads(json.dumps(NEEDS))
    needs["finance"].update(net_income_monthly=4000, savings=150_000, tin_pct=3.5, max_price=400_000)
    lid = _listing(conn, 450_000, bedrooms=3, area_m2=80)
    e = {x["id"]: x for x in scoring.rank(conn, needs)}[lid]["eval"]
    assert e["mortgage"]["effort_ratio"] > 0.35 and any("esfuerzo" in f for f in e["flags"])
    assert len(e["excluded"]) >= 3  # price, m², bedrooms
    assert e["components"]["affordability"] == 0.0


def test_amenity_score_linear():
    cfg = {"amenities": {"park": {"weight": 1, "good_m": 300, "bad_m": 1500}}}
    s, parts = scoring.amenity_score({"park": {"nearest_m": 900}}, cfg)
    assert s == pytest.approx(0.5) and parts["park"]["nearest_m"] == 900
    assert scoring.amenity_score(None, cfg)[0] is None


# ── OSM ──────────────────────────────────────────────────────────────────────
def test_overpass_summarise_and_query():
    els = [{"lat": 40.001, "lon": -3.0, "tags": {"leisure": "park", "name": "Parque Norte"}},
           {"center": {"lat": 40.01, "lon": -3.0}, "tags": {"amenity": "school"}},
           {"lat": 41.0, "lon": -3.0, "tags": {"leisure": "park"}}]  # too far, ignored
    out = overpass.summarise(els, 40.0, -3.0)
    assert out["park"]["count"] == 1 and out["park"]["nearest_name"] == "Parque Norte"
    assert 100 < out["park"]["nearest_m"] < 120 and out["school"]["nearest_m"] > 1000
    assert out["transit"]["nearest_m"] is None
    assert "around:1500" in overpass.build_query(40.0, -3.0)


# ── MCP client ───────────────────────────────────────────────────────────────
FAKE = [sys.executable, str(Path(__file__).parent / "fake_mcp.py")]


def test_mcp_roundtrip_and_ingest(conn):
    tools = idealista_mcp.schema(FAKE)
    assert tools[0]["name"] == "search_ads"
    ids = idealista_mcp.search(conn, NEEDS, FAKE, {"distance": 1000})
    row = conn.execute("SELECT * FROM listings WHERE id=?", (ids[0],)).fetchone()
    assert row["property_type"] == "chalet" and row["zone_id"] == "alcorcon" and row["price"] == 420_000


def test_mcp_tool_error_is_surfaced(conn):
    with pytest.raises(idealista_mcp.McpError, match="missing credentials"):
        idealista_mcp.search(conn, NEEDS, FAKE, {"fail": True})


def test_extract_ads_refuses_to_guess():
    with pytest.raises(idealista_mcp.McpError, match="no ad list"):
        idealista_mcp.extract_ads({"weird": "shape"})


# ── SERPAVI ──────────────────────────────────────────────────────────────────
def test_serpavi_loader_on_synthetic_workbook(conn, tmp_path):
    p = tmp_path / "serpavi.xlsx"
    mun = pd.DataFrame({"CUMUN": ["28007", "28006", "28079", "08019"], "NMUN": ["Alcorcón", "Alcobendas", "Madrid", "Barcelona"],
                        "ALQM2_LV_M_VC_23": [10.0, 11.0, 15.0, 17.0], "ALQM2_LV_M_VC_24": [10.5, 11.5, 16.0, 18.0],
                        "ALQM2_LV_M_VU_24": [9.0, None, None, 20.0]})
    dis = pd.DataFrame({"CUDIS": ["2807901", "2807907", "0801901"], "ALQM2_LV_M_VC_24": [18.0, 17.2, 19.0],
                        "ALQM2_LV_M_VU_24": [None, None, None]})
    with pd.ExcelWriter(p) as w:
        mun.to_excel(w, sheet_name="Municipios", index=False)
        dis.to_excel(w, sheet_name="Distritos", index=False)
    stats = serpavi.load(conn, str(p), {"alcorcon", "alcobendas"})
    assert stats["distritos"] == 2
    ind = db.indicators_by_zone(conn)
    assert ind["alcorcon"]["rent_m2_flat"] == 10.5 and ind["alcorcon"]["rent_m2_house"] == 9.0  # latest year wins
    assert "rent_m2_house" not in ind["alcobendas"]                    # empty cell stays empty
    assert ind["madrid/chamberi"]["rent_m2_flat"] == 17.2 and "madrid" not in ind  # city handled via districts
    assert "barcelona" not in ind


def test_serpavi_fails_loudly_on_unknown_layout(conn, tmp_path):
    p = tmp_path / "bad.xlsx"
    with pd.ExcelWriter(p) as w:
        pd.DataFrame({"x": [1]}).to_excel(w, sheet_name="Municipios", index=False)
        pd.DataFrame({"x": [1]}).to_excel(w, sheet_name="Distritos", index=False)
    with pytest.raises(ValueError, match="CUMUN"):
        serpavi.load(conn, str(p), set())


# ── Madrid CKAN ──────────────────────────────────────────────────────────────
def test_ckan_rows_pages_and_retries_403(monkeypatch):
    monkeypatch.setattr(madrid_ckan.time, "sleep", lambda s: None)
    calls = {"n": 0}

    def handler(req: httpx.Request):
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(403, text="Access Denied")
        off = int(req.url.params["offset"])
        assert json.loads(req.url.params["filters"]) == {"COD_DISTRITO": "21"}  # text values
        recs = [{"i": str(k)} for k in range(off, min(off + 2, 3))]
        return httpx.Response(200, json={"success": True, "result": {"records": recs, "total": 3, "fields": []}})

    c = httpx.Client(transport=httpx.MockTransport(handler))
    got = list(madrid_ckan.rows("200076-2-padron-csv", {"COD_DISTRITO": 21}, page=2, client=c))
    assert [r["i"] for r in got] == ["0", "1", "2"]


# ── API ──────────────────────────────────────────────────────────────────────
@pytest.fixture
def client(tmp_path):
    needs = tmp_path / "needs.yaml"
    needs.write_text((Path(__file__).parent.parent / "config" / "needs.yaml").read_text())
    return TestClient(create_app(str(tmp_path / "t.db"), str(needs)))


def test_api_end_to_end(client):
    r = client.post("/api/listings", json={"url": "https://x.test/1", "property_type": "chalet", "price": 450000,
                                           "area_m2": 180, "bedrooms": 4, "municipality": "Alcorcón", "garden": "1"})
    lid = r.json()["id"]
    client.post("/api/listings/import-csv", content="url,price,area_m2,bedrooms,property_type,municipality\nhttps://x.test/2,380000,160,4,adosado,Alcobendas\n")
    client.put("/api/zones/alcorcon/indicators", json={"notary_price_m2_house": 2400, "income_hh": 30000})
    client.put("/api/zones/alcobendas/indicators", json={"income_hh": 45000})
    L = client.get("/api/listings").json()
    assert len(L) == 2 and all("eval" in x for x in L)
    mine = next(x for x in L if x["id"] == lid)
    assert mine["eval"]["benchmark_source"] == "notarial"
    assert client.patch(f"/api/listings/{lid}", json={"status": "shortlist"}).json() == {"ok": True}
    assert client.patch(f"/api/listings/{lid}", json={"status": "bogus"}).status_code == 400
    assert client.patch("/api/listings/nope", json={"status": "new"}).status_code == 404
    Z = {z["zone_id"]: z for z in client.get("/api/zones").json()}
    assert Z["alcobendas"]["score"] is not None and Z["alcorcon"]["indicators"]["notary_price_m2_house"] == 2400
    m = client.get("/api/mortgage", params={"price": 400000, "savings": 100000, "income": 5000}).json()
    assert m["savings_shortfall"] == pytest.approx(8800)
    assert "chalet" in client.get("/api/export.csv").text
    assert client.get("/").status_code == 200
    assert client.post(f"/api/listings/{lid}/amenities").status_code == 400  # no coordinates


def test_api_needs_roundtrip_keeps_backup(client, tmp_path):
    n = client.get("/api/needs").json()
    n["finance"]["savings"] = 90000
    assert client.put("/api/needs", json=n).status_code == 200
    assert client.get("/api/needs").json()["finance"]["savings"] == 90000
    assert (tmp_path / "needs.yaml.bak").read_text().startswith("# ───")


def test_money_vs_coordinates_parsing():
    from app.util import to_money
    assert to_money("450.000") == 450_000 and to_money("1.250.000") == 1_250_000 and to_money("450000") == 450_000
    assert to_float("40.345") == 40.345  # coordinates must keep their decimal point
