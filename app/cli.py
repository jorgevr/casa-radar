"""casa-radar command line.

  python -m app.cli serve [--port 8765]
  python -m app.cli import-listings FILE.csv
  python -m app.cli import-indicators FILE.csv
  python -m app.cli serpavi --file SERPAVI.xlsx [--all-madrid-region]
  python -m app.cli mcp-schema            # print idealista-mcp tool schemas
  python -m app.cli amenities [--all]     # fetch OSM amenities for listings with coordinates
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import yaml

from . import db
from .etl import indicators as ind_etl


def _providers():
    p = Path(db.ROOT / "config" / "providers.yaml")
    return (yaml.safe_load(p.read_text()) or {}) if p.exists() else {}


def main(argv=None):
    ap = argparse.ArgumentParser(prog="casa-radar")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("serve"); s.add_argument("--port", type=int, default=8765); s.add_argument("--host", default="127.0.0.1")
    for name in ("import-listings", "import-indicators"):
        c = sub.add_parser(name); c.add_argument("file")
    sp = sub.add_parser("serpavi"); sp.add_argument("--file", required=True); sp.add_argument("--all-madrid-region", action="store_true")
    sub.add_parser("mcp-schema")
    a = sub.add_parser("amenities"); a.add_argument("--all", action="store_true", help="refetch even if cached")
    args = ap.parse_args(argv)

    if args.cmd == "serve":
        import uvicorn
        uvicorn.run("app.main:default_app", factory=True, host=args.host, port=args.port)
        return 0

    conn = db.connect()
    ind_etl.seed_madrid_districts(conn)
    needs = db.load_needs()

    if args.cmd == "import-listings":
        from .providers import csv_import
        ids = csv_import.import_csv_text(conn, Path(args.file).read_text(encoding="utf-8"), needs)
        print(f"{len(ids)} anuncios importados")
    elif args.cmd == "import-indicators":
        print(f"{ind_etl.import_csv(conn, Path(args.file).read_text(encoding='utf-8'))} indicadores importados")
    elif args.cmd == "serpavi":
        from .etl import serpavi
        g = needs.get("geography", {})
        wanted = set(g.get("preferred_zones") or []) | set(g.get("allow_zones") or []) | {
            r["zone_id"] for r in conn.execute("SELECT zone_id FROM zones")}
        print(serpavi.load(conn, args.file, wanted, args.all_madrid_region))
    elif args.cmd == "mcp-schema":
        from .providers import idealista_mcp
        cmd = (_providers().get("idealista") or {}).get("command")
        if not cmd:
            print("config/providers.yaml: define idealista.command (ver providers.example.yaml)"); return 1
        print(json.dumps(idealista_mcp.schema(cmd), indent=2, ensure_ascii=False))
    elif args.cmd == "amenities":
        from .etl import overpass
        q = "SELECT id FROM listings WHERE lat IS NOT NULL AND lon IS NOT NULL"
        if not args.all:
            q += " AND id NOT IN (SELECT listing_id FROM amenities)"
        for r in conn.execute(q).fetchall():
            try:
                overpass.refresh_listing(conn, r["id"]); print("ok", r["id"])
            except Exception as e:
                print("fallo", r["id"], e, file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
