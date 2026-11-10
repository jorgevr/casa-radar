"""casa-radar command line.

  python -m app.cli serve [--port 8765]
  python -m app.cli import-listings FILE.csv
  python -m app.cli import-indicators FILE.csv
  python -m app.cli import-emails PATH [PATH ...]   # .eml / .mbox files or folders
  python -m app.cli reprocess-emails [--failed | --all]   # re-read stored emails with the current reader
  python -m app.cli serpavi --file SERPAVI.xlsx [--all-madrid-region]
  python -m app.cli categories            # print category rules and each stored search name's category
  python -m app.cli mcp-schema           # print idealista-mcp tool schemas
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


def _plural(n, one, many):
    return f"{n} {one if n == 1 else many}"


def _cut(text, width):
    text = " ".join(str(text or "").split())
    return text if len(text) <= width else text[:width - 1] + "…"


def _problem_line(label, item, text):
    date = (item.get("alert_date") or "")[:10] or "sin fecha "
    subject = item.get("subject") or item.get("email_id") or ""
    return f"{label:<9} {date} {_cut(subject, 24):<24}  {text}"


def format_import_summary(s):
    """Summary lines of contracts/cli.md. Prints only figures the run summary holds (no 'sin cambios')."""
    lines = []
    for p in s["problems"]:
        label = "FALLO" if p["outcome"] == "failed" else "RECHAZADO"
        lines.append(_problem_line(label, p, p["reason"] or ""))
    lines += [_problem_line("AVISO", n, n["text"]) for n in s["notices"]]
    lines.append(f"{_plural(s['n_found'], 'email', 'emails')}: {_plural(s['n_imported'], 'importado', 'importados')}, "
                 f"{_plural(s['n_already'], 'ya procesado', 'ya procesados')}, "
                 f"{_plural(s['n_rejected'], 'rechazado', 'rechazados')}, {_plural(s['n_failed'], 'fallido', 'fallidos')}")
    lines.append(f"anuncios: {_plural(s['n_new_listings'], 'nuevo', 'nuevos')}, "
                 f"{_plural(s['n_updated_listings'], 'actualizado', 'actualizados')} "
                 f"({_plural(s['n_price_changes'], 'cambio', 'cambios')} de precio)")
    return lines


def main(argv=None):
    ap = argparse.ArgumentParser(prog="casa-radar")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("serve"); s.add_argument("--port", type=int, default=8765); s.add_argument("--host", default="127.0.0.1")
    for name in ("import-listings", "import-indicators"):
        c = sub.add_parser(name); c.add_argument("file")
    ie = sub.add_parser("import-emails"); ie.add_argument("paths", nargs="+", metavar="PATH")
    rp = sub.add_parser("reprocess-emails")
    grp = rp.add_mutually_exclusive_group()
    grp.add_argument("--failed", action="store_true", help="failed emails and ones an older reader rejected (default)")
    grp.add_argument("--all", action="store_true", help="every stored email")
    sp = sub.add_parser("serpavi"); sp.add_argument("--file", required=True); sp.add_argument("--all-madrid-region", action="store_true")
    sub.add_parser("categories")
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
    elif args.cmd == "import-emails":
        from . import alerts
        summary = alerts.import_paths(conn, [Path(p) for p in args.paths])
        # Subjects/reasons are email text: a console that cannot encode them must not lose the summary.
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(errors="backslashreplace")
        print(*format_import_summary(summary), sep="\n")
        return 1 if summary["n_failed"] > 0 else 0
    elif args.cmd == "reprocess-emails":
        from . import alerts
        summary = alerts.reprocess(conn, "all" if args.all else "failed")
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(errors="backslashreplace")
        print(*format_import_summary(summary), sep="\n")
        return 1 if summary["n_failed"] > 0 else 0
    elif args.cmd == "categories":
        from . import categories
        try:
            rules = categories.load_rules()
        except ValueError as exc:
            print(f"reglas de categoría ilegibles: {exc}", file=sys.stderr); return 1
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(errors="backslashreplace")
        print(f"Reglas ({len(rules)}):")
        for r in rules:
            print(f'  "{r["contains"]}" -> {r["category"]}')
        names = conn.execute("SELECT search_name, COUNT(*) AS n FROM alert_emails WHERE search_name IS NOT NULL "
                             "AND search_name <> '' GROUP BY search_name ORDER BY search_name").fetchall()
        print(f"Búsquedas ({len(names)}):")
        for n in names:
            category, _ = categories.categorise(n["search_name"], rules)
            print(f'  {category:<12} {n["n"]:>4} emails  {n["search_name"]}')
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
