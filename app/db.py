"""SQLite storage + config loading."""
from __future__ import annotations

import json
import os
import sqlite3
from datetime import date
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = os.environ.get("CASA_DB", str(ROOT / "data" / "casa.db"))
NEEDS_PATH = os.environ.get("CASA_NEEDS", str(ROOT / "config" / "needs.yaml"))

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
"""


def connect(path: str | None = None) -> sqlite3.Connection:
    p = path or DB_PATH
    if p != ":memory:":
        Path(p).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(p, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


def load_needs(path: str | None = None) -> dict:
    with open(path or NEEDS_PATH, encoding="utf-8") as f:
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
