"""Generic indicator loader + Madrid district seed.

`import_csv` is the escape hatch for every source that doesn't have a dedicated loader yet — notably the
Notariado €/m² (their portal is a JavaScript map with no documented API, so you read the number off the
map or export it) and INE's Atlas de renta. CSV columns: zone,key,value[,source,year,note]

Keys the scoring understands:
  notary_price_m2_flat | notary_price_m2_house   Notariado €/m² (plurifamiliar / unifamiliar)
  income_hh, pct_65plus, density, no2, crime_rate, rent_m2_flat, rent_m2_house   (see config/needs.yaml)
"""
from __future__ import annotations

import csv
import io

from ..db import ensure_zone, set_indicator
from ..util import slug, to_float

MADRID_DISTRICTS = {
    "01": "Centro", "02": "Arganzuela", "03": "Retiro", "04": "Salamanca", "05": "Chamartín",
    "06": "Tetuán", "07": "Chamberí", "08": "Fuencarral-El Pardo", "09": "Moncloa-Aravaca",
    "10": "Latina", "11": "Carabanchel", "12": "Usera", "13": "Puente de Vallecas", "14": "Moratalaz",
    "15": "Ciudad Lineal", "16": "Hortaleza", "17": "Villaverde", "18": "Villa de Vallecas",
    "19": "Vicálvaro", "20": "San Blas-Canillejas", "21": "Barajas",
}


def madrid_zone_id(code: str) -> str:
    return f"madrid/{slug(MADRID_DISTRICTS[code])}"


def seed_madrid_districts(conn) -> int:
    for code, name in MADRID_DISTRICTS.items():
        ensure_zone(conn, madrid_zone_id(code), f"Madrid · {name}", "Madrid", "distrito")
    conn.commit()
    return len(MADRID_DISTRICTS)


def import_csv(conn, text: str, default_source: str = "csv") -> int:
    text = text.lstrip("﻿")
    delim = ";" if text[:2048].count(";") > text[:2048].count(",") else ","
    n = 0
    for row in csv.DictReader(io.StringIO(text), delimiter=delim):
        row = {(k or "").strip().lower(): v for k, v in row.items()}
        zone, key, val = (row.get("zone") or "").strip(), (row.get("key") or "").strip(), to_float(row.get("value"))
        if not zone or not key or val is None:
            continue
        ensure_zone(conn, zone)
        year = int(float(row["year"])) if row.get("year") else None
        set_indicator(conn, zone, key, val, row.get("source") or default_source, year, row.get("note"))
        n += 1
    conn.commit()
    return n
