"""SQLite storage + config loading."""
from __future__ import annotations

import json
import os
import shutil
import sqlite3
from datetime import date
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = os.environ.get("CASA_DB", str(ROOT / "data" / "casa.db"))
NEEDS_PATH = os.environ.get("CASA_NEEDS", str(ROOT / "config" / "needs.yaml"))
NEEDS_EXAMPLE_PATH = ROOT / "config" / "needs.example.yaml"

SCHEMA = """
CREATE TABLE IF NOT EXISTS zones(
  zone_id TEXT PRIMARY KEY, name TEXT, municipality TEXT, level TEXT
);
CREATE TABLE IF NOT EXISTS indicators(
  zone_id TEXT, key TEXT, value REAL, source TEXT, year INTEGER, note TEXT,
  PRIMARY KEY(zone_id, key)
);
CREATE TABLE IF NOT EXISTS listings(
  id TEXT PRIMARY KEY, source TEXT, url TEXT, title TEXT, property_type TEXT,
  price REAL, area_m2 REAL, bedrooms INTEGER, bathrooms INTEGER, plot_m2 REAL,
  garden INTEGER, new_build INTEGER, lat REAL, lon REAL,
  municipality TEXT, district TEXT, neighborhood TEXT, zone_id TEXT,
  status TEXT DEFAULT 'new', notes TEXT DEFAULT '',
  first_seen TEXT, last_seen TEXT, raw TEXT
);
CREATE TABLE IF NOT EXISTS price_history(listing_id TEXT, day TEXT, price REAL);
CREATE TABLE IF NOT EXISTS amenities(listing_id TEXT PRIMARY KEY, data TEXT, fetched TEXT);
CREATE TABLE IF NOT EXISTS import_runs(
  run_id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT, started_at TEXT, finished_at TEXT,
  status TEXT, error TEXT, n_found INTEGER DEFAULT 0, n_imported INTEGER DEFAULT 0,
  n_already INTEGER DEFAULT 0, n_rejected INTEGER DEFAULT 0, n_failed INTEGER DEFAULT 0,
  n_new_listings INTEGER DEFAULT 0, n_updated_listings INTEGER DEFAULT 0,
  n_price_changes INTEGER DEFAULT 0, notes TEXT DEFAULT '[]'
);
CREATE TABLE IF NOT EXISTS alert_emails(
  email_id TEXT PRIMARY KEY, mailbox_id TEXT UNIQUE, content_hash TEXT, origin TEXT, file_name TEXT,
  sender TEXT, subject TEXT, search_name TEXT, alert_date TEXT, forwarded INTEGER DEFAULT 0,
  alert_type TEXT, outcome TEXT, reason TEXT, reader_version TEXT, category TEXT,
  category_rules_matched TEXT, raw BLOB, first_run_id INTEGER, last_run_id INTEGER
);
CREATE TABLE IF NOT EXISTS sightings(
  email_id TEXT, listing_id TEXT, alert_type TEXT, seen_at TEXT, price REAL, previous_price REAL,
  area_m2 REAL, bedrooms INTEGER, floor INTEGER, exterior INTEGER, elevator INTEGER, garage INTEGER,
  type_text TEXT, property_type TEXT, new_build_stated INTEGER, development INTEGER,
  unit_description TEXT, location_text TEXT, link_tracking TEXT, link_direct TEXT,
  unrecognised TEXT DEFAULT '[]', category TEXT, raw_block TEXT,
  PRIMARY KEY(email_id, listing_id)
);
CREATE INDEX IF NOT EXISTS sightings_listing ON sightings(listing_id);
CREATE TABLE IF NOT EXISTS mailbox_state(
  id INTEGER PRIMARY KEY CHECK(id = 1), provider TEXT, account TEXT, label_name TEXT, label_id TEXT,
  auth_state TEXT DEFAULT 'not_configured', auto_sync TEXT DEFAULT 'on', backfill_from TEXT,
  last_attempt_at TEXT, last_attempt_status TEXT, last_success_at TEXT, last_error_at TEXT,
  last_error TEXT, running_run_id INTEGER, progress_done INTEGER, progress_total INTEGER
);
"""

# Columns added to existing tables by feature 001 (data-model.md); nullable so old databases keep working.
ADDED_COLUMNS = {
    "listings": [
        ("floor", "INTEGER"), ("exterior", "INTEGER"), ("elevator", "INTEGER"), ("garage", "INTEGER"),
        ("terrace", "INTEGER"), ("pool", "INTEGER"), ("location_text", "TEXT"), ("development", "INTEGER"),
        ("unit_description", "TEXT"), ("new_build_origin", "TEXT"), ("field_sources", "TEXT"),
        ("published_at", "TEXT"), ("price_updated_at", "TEXT"), ("categories", "TEXT"),
        ("availability", "TEXT DEFAULT 'active'"), ("availability_changed_at", "TEXT"),
        ("merged_into", "TEXT"), ("alert_flags", "TEXT"), ("first_run_id", "INTEGER"),
    ],
    "price_history": [("origin", "TEXT"), ("email_id", "TEXT")],
}


def connect(path: str | None = None) -> sqlite3.Connection:
    p = path or DB_PATH
    if p != ":memory:":
        Path(p).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(p, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    migrate(conn)
    return conn


def migrate(conn) -> None:
    """Add the columns of ADDED_COLUMNS that an existing database lacks (idempotent)."""
    for table, columns in ADDED_COLUMNS.items():
        have = {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
        for name, decl in columns:
            if name not in have:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {decl}")
    conn.commit()


def load_needs(path: str | None = None) -> dict:
    p = Path(path or NEEDS_PATH)
    if not p.exists():  # fresh clone: needs.yaml is personal and untracked, start from the example
        p.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(NEEDS_EXAMPLE_PATH, p)
    with open(p, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def save_needs(needs: dict, path: str | None = None) -> None:
    p = Path(path or NEEDS_PATH)
    bak = p.with_suffix(p.suffix + ".bak")
    if p.exists() and not bak.exists():  # yaml.safe_dump drops comments: keep the commented original once
        bak.write_bytes(p.read_bytes())
    with open(p, "w", encoding="utf-8") as f:
        yaml.safe_dump(needs, f, allow_unicode=True, sort_keys=False)


def today() -> str:
    return date.today().isoformat()


def set_indicator(conn, zone_id, key, value, source="manual", year=None, note=None):
    conn.execute(
        "INSERT INTO indicators(zone_id,key,value,source,year,note) VALUES(?,?,?,?,?,?) "
        "ON CONFLICT(zone_id,key) DO UPDATE SET value=excluded.value, source=excluded.source, "
        "year=excluded.year, note=excluded.note",
        (zone_id, key, value, source, year, note),
    )


def ensure_zone(conn, zone_id, name=None, municipality=None, level=None):
    conn.execute(
        "INSERT OR IGNORE INTO zones(zone_id,name,municipality,level) VALUES(?,?,?,?)",
        (zone_id, name or zone_id, municipality, level),
    )


def indicators_by_zone(conn) -> dict[str, dict[str, float]]:
    out: dict[str, dict[str, float]] = {}
    for r in conn.execute("SELECT zone_id,key,value FROM indicators WHERE value IS NOT NULL"):
        out.setdefault(r["zone_id"], {})[r["key"]] = r["value"]
    return out


def dumps(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, default=str)
