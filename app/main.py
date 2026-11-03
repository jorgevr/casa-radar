"""FastAPI app: JSON API + the static single-page UI. Run: python -m app.cli serve"""
from __future__ import annotations

import base64
import binascii
import json
import os
import re
import tempfile
from pathlib import Path

import yaml
from fastapi import Body, FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles

from typing import Any

from . import alerts, categories, db, derive, mortgage, scoring
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
    def merge_groups() -> dict[str, list[str]]:
        """Final live target id -> ids merged into it (chains resolved; members of a cycle have no target)."""
        into = {r["id"]: r["merged_into"] for r in conn.execute(
            "SELECT id, merged_into FROM listings WHERE merged_into IS NOT NULL AND merged_into <> ''")}
        groups: dict[str, list[str]] = {}
        for src, cur in into.items():
            seen = {src}
            while cur in into and cur not in seen:
                seen.add(cur)
                cur = into[cur]
            if cur not in into:
                groups.setdefault(cur, []).append(src)
        return groups

    def with_provenance(rows: list[dict]) -> list[dict]:
        """Add `links` (direct and tracking, merged listings included) and `sightings` (newest first)."""
        groups = merge_groups()
        urls = {r["id"]: r["url"] for r in conn.execute("SELECT id, url FROM listings")}
        by_listing: dict[str, list] = {}
        for r in conn.execute(
                "SELECT s.listing_id, s.link_direct, s.link_tracking, a.alert_date, a.subject "
                "FROM sightings s JOIN alert_emails a ON a.email_id = s.email_id "
                "ORDER BY a.alert_date DESC, s.rowid DESC"):
            by_listing.setdefault(r["listing_id"], []).append(r)
        for l in rows:
            ids = [l["id"], *groups.get(l["id"], [])]
            direct = [urls[i] for i in ids if urls.get(i)]
            tracking: list[str] = []
            sightings = []
            for r in sorted((r for i in ids for r in by_listing.get(i, [])),
                            key=lambda r: r["alert_date"] or "", reverse=True):
                direct.append(r["link_direct"])
                tracking.append(r["link_tracking"])
                sightings.append({"alert_date": r["alert_date"], "subject": r["subject"]})
            l["links"] = {"direct": list(dict.fromkeys(u for u in direct if u)),
                          "tracking": list(dict.fromkeys(u for u in tracking if u))}
            l["sightings"] = sightings
        return rows

    @app.post("/api/listings/{lid:path}/merge")
    def merge_listing(lid: str, body: dict = Body(...)):
        into = body.get("into")
        if not isinstance(into, str) or not into:
            raise HTTPException(400, 'se esperaba {"into": "<id del anuncio>"}')
        if conn.execute("SELECT 1 FROM listings WHERE id=?", (lid,)).fetchone() is None:
            raise HTTPException(404, "listing not found")
        if conn.execute("SELECT 1 FROM listings WHERE id=?", (into,)).fetchone() is None:
            raise HTTPException(404, "target listing not found")
        if into == lid:
            raise HTTPException(400, "a listing cannot be merged into itself")
        seen, cur = {lid}, into  # walk the target's chain; reaching lid would close a cycle
        while cur:
            if cur in seen:
                raise HTTPException(409, "merge would create a cycle")
            seen.add(cur)
            row = conn.execute("SELECT merged_into FROM listings WHERE id=?", (cur,)).fetchone()
            cur = row["merged_into"] if row else None
        conn.execute("UPDATE listings SET merged_into=? WHERE id=?", (into, lid))
        conn.commit()
        return {"ok": True, "id": lid, "merged_into": into}

    @app.get("/api/listings/{lid:path}/price-history")
    def price_history(lid: str):
        if conn.execute("SELECT 1 FROM listings WHERE id=?", (lid,)).fetchone() is None:
            raise HTTPException(404, "listing not found")
        # Same ordering as scoring.py (data-model "Extended: price_history"); duplicated, not shared.
        rows = conn.execute(
            "SELECT day, price, origin FROM price_history WHERE listing_id=? "
            "ORDER BY day, (origin = 'alert_previous') DESC, rowid", (lid,))
        return [{"day": r["day"], "price": r["price"], "origin": r["origin"]} for r in rows]

    @app.get("/api/listings")
    def listings():
        return with_provenance(scoring.rank(conn, needs()))

    @app.post("/api/listings")
    def add_listing(body: dict = Body(...)):
        return {"id": upsert_listing(conn, body, "manual", needs())}

    @app.post("/api/listings/import-csv")
    async def import_listings(request: Request):
        text = (await request.body()).decode("utf-8", errors="replace")
        ids = csv_import.import_csv_text(conn, text, needs())
        return {"imported": len(ids)}

    def categories_view():
        try:
            rules = categories.load_rules()
        except ValueError as exc:  # malformed rules file: a clear message, not a traceback
            raise HTTPException(500, f"alert category rules unreadable: {exc}")
        names = conn.execute(
            "SELECT search_name AS name, MIN(category) AS category, COUNT(*) AS emails FROM alert_emails "
            "WHERE search_name IS NOT NULL AND search_name <> '' GROUP BY search_name ORDER BY search_name").fetchall()
        return {"rules": rules,
                "search_names": [{"name": r["name"], "category": r["category"] or categories.UNKNOWN,
                                  "emails": r["emails"]} for r in names]}

    @app.get("/api/categories")
    def get_categories():
        return categories_view()

    @app.put("/api/categories")
    def put_categories(body: Any = Body(...)):
        if not isinstance(body, dict) or "rules" not in body:
            raise HTTPException(400, 'body must be {"rules": [{"contains": ..., "category": ...}]}')
        try:
            rules = categories.validate_rules(body["rules"], "rules")
        except ValueError as exc:
            raise HTTPException(400, str(exc))
        categories.save_rules(rules)  # atomic: temp file + replace
        try:
            categories.recategorise_all(conn)  # FR-031: all stored emails, no re-import
        except ValueError as exc:
            raise HTTPException(500, f"alert category rules unreadable: {exc}")
        return categories_view()

    @app.patch("/api/listings/{lid:path}")
    def patch_listing(lid: str, body: dict = Body(...)):
        if conn.execute("SELECT 1 FROM listings WHERE id=?", (lid,)).fetchone() is None:
            raise HTTPException(404, "listing not found")
        if "new_build" in body and body["new_build"] is not None and not isinstance(body["new_build"], bool):
            raise HTTPException(400, "new_build must be true | false | null")
        if "status" in body and body["status"] not in {"new", "shortlist", "discarded"}:
            raise HTTPException(400, "status must be new | shortlist | discarded")
        if "availability" in body and (not isinstance(body["availability"], str)
                                       or body["availability"] not in {"active", "gone"}):
            raise HTTPException(400, "availability must be active | gone")
        for k in ("status", "notes"):
            if k in body:
                conn.execute(f"UPDATE listings SET {k}=? WHERE id=?", (body[k], lid))
        if "availability" in body:  # only the user changes availability (FR-019); the date records each change
            conn.execute("UPDATE listings SET availability=?, availability_changed_at=? WHERE id=?",
                         (body["availability"], db.today(), lid))
            derive.derive_listing(conn, lid)  # refresh the relisted flag against the new mark
        if "new_build" in body:  # FR-033: a user value (origin 'user'); null clears it and the derivation decides again
            v = body["new_build"]
            conn.execute("UPDATE listings SET new_build=?, new_build_origin=? WHERE id=?",
                         (None, None, lid) if v is None else (int(v), "user", lid))
            derive.derive_listing(conn, lid)
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

    # ── alert emails: file import and runs ──────────────────────────────────
    def run_detail(run_id: int):
        row = conn.execute("SELECT * FROM import_runs WHERE run_id=?", (run_id,)).fetchone()
        if row is None:
            return None
        out = dict(row)
        notes = json.loads(out.pop("notes") or "[]")
        subj = {r["email_id"]: r for r in conn.execute(
            "SELECT email_id, subject, alert_date FROM alert_emails WHERE first_run_id=? OR last_run_id=?",
            (run_id, run_id))}
        file_failures = [n for n in notes if n.get("outcome") == "failed"]  # whole files: no alert_emails row
        notes = [n for n in notes if "text" in n]
        out["problems"] = [dict(r) for r in conn.execute(
            "SELECT email_id, alert_date, subject, outcome, reason FROM alert_emails "
            "WHERE first_run_id=? AND outcome IN ('rejected','failed') ORDER BY rowid", (run_id,))]
        out["problems"] += [{"email_id": n["email_id"], "alert_date": None, "subject": None,
                             "outcome": "failed", "reason": n["reason"]} for n in file_failures]
        out["notices"] = [{"email_id": n["email_id"], "alert_date": subj[n["email_id"]]["alert_date"] if n["email_id"] in subj else None,
                           "subject": subj[n["email_id"]]["subject"] if n["email_id"] in subj else None, "text": n["text"]} for n in notes]
        return out

    @app.post("/api/alerts/import")
    async def import_alerts(request: Request):
        bad = HTTPException(400, 'se esperaba {"files": [{"name": str, "content_base64": str}, ...]}')
        try:
            files = (await request.json()).get("files")
        except (ValueError, AttributeError):
            raise bad from None
        if not isinstance(files, list) or not files:
            raise bad
        decoded = []
        for f in files:
            if not (isinstance(f, dict) and isinstance(f.get("name"), str) and isinstance(f.get("content_base64"), str)):
                raise bad
            try:
                decoded.append((f["name"], base64.b64decode(f["content_base64"], validate=True)))
            except (binascii.Error, ValueError):
                raise bad from None
        with tempfile.TemporaryDirectory(prefix="casa-import-") as tmp:
            paths = []
            for i, (name, raw) in enumerate(decoded):
                safe = re.sub(r"[^\w.\- ]", "_", name.replace("\\", "/").rsplit("/", 1)[-1]).strip() or "file"
                (Path(tmp) / str(i)).mkdir()
                paths.append(Path(tmp) / str(i) / safe)
                paths[-1].write_bytes(raw)
            summary = alerts.import_paths(conn, paths, kind="file_ui")
        return summary

    @app.get("/api/runs")
    def list_runs(limit: int = Query(20, ge=1, le=500)):
        ids = [r[0] for r in conn.execute("SELECT run_id FROM import_runs ORDER BY run_id DESC LIMIT ?", (limit,))]
        return [run_detail(i) for i in ids]

    @app.get("/api/runs/{run_id}")
    def get_run(run_id: int):
        out = run_detail(run_id)
        if out is None:
            raise HTTPException(404, "run not found")
        return out

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
        w.writerow(["score", "excluded", "zone", "type", "price", "area_m2", "price_m2", "bedrooms", "url", "flags",
                    "published_at", "price_updated_at", "found_via", "scoring_version"])
        for l in scoring.rank(conn, needs()):
            e = l["eval"]
            w.writerow([None if e["score"] is None else round(e["score"]), "; ".join(e["excluded"]), l["zone_id"],
                        l["property_type"], l["price"], l["area_m2"], e["price_m2"] and round(e["price_m2"]),
                        l["bedrooms"], l["url"], " | ".join(e["flags"]),
                        l.get("published_at"), l.get("price_updated_at"), "", scoring.SCORING_VERSION])
        return buf.getvalue()

    @app.get("/")
    def index():
        return FileResponse(STATIC / "index.html")

    app.mount("/static", StaticFiles(directory=STATIC), name="static")
    return app


def default_app() -> FastAPI:  # for `uvicorn app.main:default_app --factory`
    return create_app()
