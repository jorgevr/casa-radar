"""Manual / CSV listing ingestion — the path that works with no credentials.

Columns (any subset; Spanish or English headers are fine):
url,title,property_type,price,area_m2,bedrooms,bathrooms,plot_m2,garden,new_build,lat,lon,municipality,district,neighborhood
"""
from __future__ import annotations

import csv
import io

from ..listings import upsert_listing


def import_csv_text(conn, text: str, needs: dict, source: str = "manual") -> list[str]:
    text = text.lstrip("﻿")
    sample = text[:2048]
    delimiter = ";" if sample.count(";") > sample.count(",") else ","
    reader = csv.DictReader(io.StringIO(text), delimiter=delimiter)
    ids = []
    for row in reader:
        row = {(k or "").strip().lower(): v for k, v in row.items()}
        if not any(row.values()):
            continue
        ids.append(upsert_listing(conn, row, source, needs))
    return ids
