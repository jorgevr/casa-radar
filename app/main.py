"""FastAPI app: JSON API + the static single-page UI. Run: python -m app.cli serve"""
from __future__ import annotations

import os
from pathlib import Path

import yaml
from fastapi import Body, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles

from . import db, mortgage, scoring
from .etl import indicators as ind_etl
from .etl import overpass
from .listings import upsert_listing
from .providers import csv_import

STATIC = Path(__file__).parent / "static"
PROVIDERS_PATH = os.environ.get("CASA_PROVIDERS", str(db.ROOT / "config" / "providers.yaml"))


def create_app(db_path: str | None = None, needs_path: str | None = None) -> FastAPI:
    app = FastAPI(title="Casa Radar")
    conn = db.connect(db_path)
    ind_etl.seed_madrid_districts(conn)

    def needs() -> dict:
        return db.load_needs(needs_path)

    @app.get("/api/needs")
    def get_needs():
        return needs()

    @app.put("/api/needs")
    def put_needs(body: dict = Body(...)):
        db.save_needs(body, needs_path)
        return {"ok": True}

    # ── listings ────────────────────────────────────────────────────────────
    @app.get("/api/listings")
    def listings():
        return scoring.rank(conn, needs())

    @app.post("/api/listings")
    def add_listing(body: dict = Body(...)):
        return {"id": upsert_listing(conn, body, "manual", needs())}

    @app.post("/api/listings/import-csv")
    async def import_listings(request: Request):
        text = (await request.body()).decode("utf-8", errors="replace")
        ids = csv_import.import_csv_text(conn, text, needs())
        return {"imported": len(ids)}

    @app.patch("/api/listings/{lid:path}")
    def patch_listing(lid: str, body: dict = Body(...)):
        if conn.execute("SELECT 1 FROM listings WHERE id=?", (lid,)).fetchone() is None:
            raise HTTPException(404, "listing not found")
        if "status" in body and body["status"] not in {"new", "shortlist", "discarded"}:
            raise HTTPException(400, "status must be new | shortlist | discarded")
        for k in ("status", "notes"):
            if k in body:
                conn.execute(f"UPDATE listings SET {k}=? WHERE id=?", (body[k], lid))
        conn.commit()
        return {"ok": True}

    @app.post("/api/listings/{lid:path}/amenities")
    def listing_amenities(lid: str):
        try:
            return overpass.refresh_listing(conn, lid)
        except ValueError as e:
            raise HTTPException(400, str(e)) from e
        except Exception as e:  # network / Overpass errors
            raise HTTPException(502, f"Overpass: {e}") from e

    # ── zones & indicators ──────────────────────────────────────────────────
    @app.get("/api/zones")
    def zones():
        return scoring.zone_table(conn, needs())

    @app.put("/api/zones/{zone_id:path}/indicators")
    def set_zone_indicators(zone_id: str, body: dict = Body(...)):
        db.ensure_zone(conn, zone_id)
        for key, val in body.items():
            if val is None or val == "":
                conn.execute("DELETE FROM indicators WHERE zone_id=? AND key=?", (zone_id, key))
            else:
                db.set_indicator(conn, zone_id, key, float(val), "manual")
        conn.commit()
        return {"ok": True}

    @app.post("/api/indicators/import-csv")
    async def import_indicators(request: Request):
        text = (await request.body()).decode("utf-8", errors="replace")
        return {"imported": ind_etl.import_csv(conn, text)}

    # ── mortgage ────────────────────────────────────────────────────────────
    @app.get("/api/mortgage")
    def mortgage_calc(price: float, savings: float, years: int = 30, tin: float = 3.0,
                      income: float | None = None, new_build: bool = False):
        n = needs()
        rates = mortgage.CostRates(**{k: v for k, v in (n.get("costs") or {}).items()
                                      if k in mortgage.CostRates.__dataclass_fields__})
        return mortgage.simulate(price, savings, years, tin, income, new_build, rates)

    @app.get("/api/providers")
    def providers_status():
        p = yaml.safe_load(open(PROVIDERS_PATH)) if Path(PROVIDERS_PATH).exists() else {}
        return {"idealista_configured": bool((p or {}).get("idealista", {}).get("command"))}

    @app.post("/api/providers/idealista/search")
    def idealista_search(body: dict = Body(default={})):
        from .providers import idealista_mcp

        if not Path(PROVIDERS_PATH).exists():
            raise HTTPException(400, "falta config/providers.yaml (copia providers.example.yaml)")
        cfg = (yaml.safe_load(open(PROVIDERS_PATH)) or {}).get("idealista") or {}
        if not cfg.get("command"):
            raise HTTPException(400, "providers.yaml: idealista.command vacío")
        args = {**(cfg.get("search_args") or {}), **body}
        try:
            ids = idealista_mcp.search(conn, needs(), cfg["command"], args, cfg.get("tool", "search_ads"))
        except Exception as e:
            raise HTTPException(502, str(e)) from e
        return {"imported": len(ids)}

    @app.get("/api/export.csv", response_class=PlainTextResponse)
    def export_csv():
        import csv
        import io

        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["score", "excluded", "zone", "type", "price", "area_m2", "price_m2", "bedrooms", "url", "flags"])
        for l in scoring.rank(conn, needs()):
            e = l["eval"]
            w.writerow([None if e["score"] is None else round(e["score"]), "; ".join(e["excluded"]), l["zone_id"],
                        l["property_type"], l["price"], l["area_m2"], e["price_m2"] and round(e["price_m2"]),
                        l["bedrooms"], l["url"], " | ".join(e["flags"])])
        return buf.getvalue()

    @app.get("/")
    def index():
        return FileResponse(STATIC / "index.html")

    app.mount("/static", StaticFiles(directory=STATIC), name="static")
    return app


def default_app() -> FastAPI:  # for `uvicorn app.main:default_app --factory`
    return create_app()
