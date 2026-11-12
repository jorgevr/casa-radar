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
  python -m app.cli mailbox-setup [--label NAME]   # authorise the mailbox (read-only) and choose the folder
  python -m app.cli sync [--wait]          # sync the mailbox now; exit 0 ok, 1 email failed, 2 stopped, 3 running
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from datetime import datetime, timedelta
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


SYNC_WAIT_TIMEOUT_SECONDS = 600     # `sync --wait`: give up (exit 3) after 10 minutes
SYNC_WAIT_POLL_SECONDS = 5          # `sync --wait`: pause between checks of the running state
_ACCOUNT_RE = re.compile(r"[^\s@]+@[^\s@]+")
# Fixed Spanish text per sync error code: stored error text and exception messages are never printed.
_SYNC_ERRORS = {
    "auth_revoked": "autorización revocada: vuelve a autorizar el buzón con mailbox-setup",
    "folder_not_found": "carpeta no encontrada: revisa el nombre con mailbox-setup --label NOMBRE",
    "source_unavailable": "buzón no disponible: inténtalo de nuevo más tarde",
}
_SYNC_ERROR_UNKNOWN = "la sincronización se detuvo por un error"


def _clock():
    return datetime.now()


def _sleep(seconds):
    time.sleep(seconds)


def _stdin_is_tty(stream):
    return bool(getattr(stream, "isatty", lambda: False)())


def _authorize():
    from .mailbox import oauth
    oauth.authorize()


def _make_source(conn, state=None):
    """The configured mail source (Gmail, read-only). Heavy imports stay lazy."""
    import httpx
    from .mailbox import gmail, oauth
    client = httpx.Client(base_url=gmail.BASE_URL, timeout=30.0)
    return gmail.GmailSource(client=client, access_token=oauth.access_token)


def _run_sync(conn, source, kind="sync_manual"):
    from . import alerts_sync
    return alerts_sync.sync(conn, source, kind)


def _run_detail(conn, run_id):
    """Stored import run with problems/notices, as the runs API and import-emails present it."""
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
        f"WHERE {'last_run_id' if out['kind'] == 'reprocess' else 'first_run_id'}=? "
        "AND outcome IN ('rejected','failed') ORDER BY rowid", (run_id,))]
    for n in file_failures:
        stored = conn.execute("SELECT alert_date, subject FROM alert_emails WHERE email_id=?",
                              (n["email_id"],)).fetchone()
        out["problems"].append({"email_id": n["email_id"], "alert_date": stored["alert_date"] if stored else None,
                                "subject": stored["subject"] if stored else None,
                                "outcome": "failed", "reason": n["reason"]})
    out["notices"] = [{"email_id": n["email_id"], "alert_date": subj[n["email_id"]]["alert_date"] if n["email_id"] in subj else None,
                       "subject": subj[n["email_id"]]["subject"] if n["email_id"] in subj else None, "text": n["text"]} for n in notes]
    return out


def _sync_is_running(conn):
    """True when mailbox_state names a run whose import_runs row is still 'running' (stale ids do not count)."""
    row = conn.execute("SELECT running_run_id FROM mailbox_state WHERE id=1").fetchone()
    if row is None or row[0] is None:
        return False
    run = conn.execute("SELECT status FROM import_runs WHERE run_id=?", (row[0],)).fetchone()
    return run is not None and run[0] == "running"


def _safe_output():
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="backslashreplace")


def _fmt_time(value):
    try:
        return datetime.fromisoformat(value).strftime("%Y-%m-%d %H:%M")
    except (TypeError, ValueError):
        return str(value)


def _mailbox_setup(conn, label):
    from . import alerts_sync
    from .mailbox import AuthRevoked, FolderNotFound, SourceUnavailable
    _safe_output()
    if not label:
        if not _stdin_is_tty(sys.stdin):
            print("Falta la carpeta del buzón: indica --label NOMBRE (nombre de la etiqueta de Gmail).",
                  file=sys.stderr)
            return 2
        print("Nombre de la etiqueta de Gmail con las alertas: ", end="", flush=True)
        label = sys.stdin.readline().strip()
        if not label:
            print("No se indicó ninguna etiqueta; indica --label NOMBRE.", file=sys.stderr)
            return 2
    try:
        _authorize()
        source = _make_source(conn, alerts_sync.read_state(conn))
        account = source.account()
        folder_id = source.resolve_folder(label)
    except AuthRevoked:
        print("No se pudo autorizar el buzón: autorización rechazada o revocada; vuelve a intentarlo.", file=sys.stderr)
        return 2
    except FolderNotFound:
        print(f"No se encontró la carpeta {label} en el buzón.", file=sys.stderr)
        return 2
    except SourceUnavailable:
        print("Buzón no disponible: inténtalo de nuevo más tarde.", file=sys.stderr)
        return 2
    except Exception as exc:  # class name only: messages may carry tokens or paths
        print(f"Autorización no completada ({type(exc).__name__}).", file=sys.stderr)
        return 2
    account = account if isinstance(account, str) and _ACCOUNT_RE.fullmatch(account) else None
    conn.execute("INSERT OR IGNORE INTO mailbox_state(id) VALUES(1)")
    conn.commit()
    alerts_sync.write_state(conn, provider="gmail", account=account, label_name=label, label_id=folder_id,
                            auth_state="valid", auto_sync="on", last_error=None, last_error_at=None)
    print(f"Cuenta: {account or 'desconocida'}")
    print(f"Carpeta: {label} (id {folder_id})")
    print("Permiso: solo lectura de Gmail, revocable en myaccount.google.com/permissions")
    return 0


def _sync_command(conn, wait):
    from . import alerts_sync
    _safe_output()
    if alerts_sync.read_state(conn) is None:
        print("El buzón no está configurado: ejecuta mailbox-setup --label NOMBRE.", file=sys.stderr)
        return 2
    if _sync_is_running(conn):
        if not wait:
            print("Ya hay una sincronización en curso.", file=sys.stderr)
            return 3
        deadline = _clock() + timedelta(seconds=SYNC_WAIT_TIMEOUT_SECONDS)
        while _sync_is_running(conn):
            if _clock() >= deadline:
                print("Se agotó la espera: sigue habiendo una sincronización en curso.", file=sys.stderr)
                return 3
            _sleep(SYNC_WAIT_POLL_SECONDS)
    try:
        result = _run_sync(conn, _make_source(conn, alerts_sync.read_state(conn)), "sync_manual")
    except Exception as exc:  # class name only: messages may carry tokens or email text
        print(f"Sincronización detenida: error inesperado ({type(exc).__name__}).", file=sys.stderr)
        return 2
    if result["status"] == "already_running":
        print("Ya hay una sincronización en curso.", file=sys.stderr)
        return 3
    if result["status"] == "error":
        print(f"Sincronización detenida: {_SYNC_ERRORS.get(result.get('error'), _SYNC_ERROR_UNKNOWN)}.",
              file=sys.stderr)
        return 2
    detail = _run_detail(conn, result.get("run_id"))
    if detail is None:
        print("Sincronización terminada, pero no se encontró su registro.", file=sys.stderr)
        return 1
    print(*format_import_summary(detail), sep="\n")
    last = (alerts_sync.read_state(conn) or {}).get("last_success_at")
    if last:
        print(f"Última sincronización correcta: {_fmt_time(last)}")
    return 1 if detail["n_failed"] > 0 else 0


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
    ms = sub.add_parser("mailbox-setup"); ms.add_argument("--label", metavar="NAME")
    sy = sub.add_parser("sync"); sy.add_argument("--wait", action="store_true", help="wait for a running sync, then sync")
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
    elif args.cmd == "mailbox-setup":
        return _mailbox_setup(conn, args.label)
    elif args.cmd == "sync":
        return _sync_command(conn, args.wait)
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
