"""SERPAVI (Ministerio de Vivienda) rent per m² by municipality / district -> rent_m2_flat, rent_m2_house.

Source details come from the catalog fiche `mivau-precios-vivienda-alquiler`, not from my own download of
the file (the sandbox I built this in can't reach cdn.mivau.gob.es). What the fiche says, which this relies on:
  * one xlsx with sheets Metadatos, CCAA, Provincias, Municipios, Distritos, Secciones censales (~71 MB);
  * codes as text: CUMUN (5 digits), CUDIS (7 digits), CUSEC (10 digits);
  * indicator columns like ALQM2_LV_M_VC_24 = median €/month per m², vivienda colectiva (flats);
    ..._VU_24 = vivienda unifamiliar (houses); suffix = year;
  * values are empty when there are fewer than 10 rentals.
The file name changes with each release: download it from the SERPAVI page and pass --file.
The loader fails loudly (printing the columns it found) rather than guessing, so the first run on the real
file is the verification step.
"""
from __future__ import annotations

import re
from pathlib import Path

import pandas as pd

from ..db import ensure_zone, set_indicator
from ..util import slug, to_float
from .indicators import MADRID_DISTRICTS, madrid_zone_id

IND_RE = re.compile(r"^ALQM2_LV_M_(VC|VU)_(\d{2})$", re.I)
NAME_CANDIDATES = ("NMUN", "LITMUN", "NOMBRE", "NOM_MUN", "MUNICIPIO", "NAME")


def _engine():
    try:
        import python_calamine  # noqa: F401
        return "calamine"
    except ImportError:
        return None  # pandas picks openpyxl; slow on a 71 MB file


def _sheet(xls: pd.ExcelFile, wanted: str) -> str:
    for s in xls.sheet_names:
        if wanted.lower() in s.lower():
            return s
    raise ValueError(f"sheet containing '{wanted}' not found; sheets: {xls.sheet_names}")


def _latest(df: pd.DataFrame, kind: str):
    cols = [(int(m.group(2)), c) for c in df.columns if (m := IND_RE.match(str(c))) and m.group(1).upper() == kind]
    for year, col in sorted(cols, reverse=True):
        if df[col].notna().any():
            return year, col
    return None, None


def load(conn, path: str, wanted_zones: set[str], create_all_madrid_region: bool = False) -> dict:
    xls = pd.ExcelFile(path, engine=_engine())
    stats = {"municipios": 0, "distritos": 0, "skipped": 0}

    # municipalities
    mun = xls.parse(_sheet(xls, "municipio"), dtype={"CUMUN": str})
    name_col = next((c for c in mun.columns if str(c).upper() in NAME_CANDIDATES), None)
    if "CUMUN" not in mun.columns or name_col is None:
        raise ValueError(f"Municipios sheet: need CUMUN + one of {NAME_CANDIDATES}; found {list(mun.columns)[:25]}")
    for kind, key in (("VC", "rent_m2_flat"), ("VU", "rent_m2_house")):
        year, col = _latest(mun, kind)
        if col is None:
            continue
        for _, r in mun.iterrows():
            cumun = str(r["CUMUN"]).zfill(5)
            if not cumun.startswith("28") or cumun == "28079":
                continue
            zid = slug(r[name_col])
            v = to_float(r[col])
            if v is None:
                continue
            if zid in wanted_zones or create_all_madrid_region:
                ensure_zone(conn, zid, str(r[name_col]), str(r[name_col]), "municipio")
                set_indicator(conn, zid, key, v, "SERPAVI", year, f"{col}")
                stats["municipios"] += 1
            else:
                stats["skipped"] += 1

    # Madrid city districts (identified by code, not by name)
    dis = xls.parse(_sheet(xls, "distrito"), dtype={"CUDIS": str, "CUMUN": str})
    if "CUDIS" not in dis.columns:
        raise ValueError(f"Distritos sheet: CUDIS column missing; found {list(dis.columns)[:25]}")
    for kind, key in (("VC", "rent_m2_flat"), ("VU", "rent_m2_house")):
        year, col = _latest(dis, kind)
        if col is None:
            continue
        for _, r in dis.iterrows():
            cudis = str(r["CUDIS"]).zfill(7)
            if not cudis.startswith("28079") or cudis[5:7] not in MADRID_DISTRICTS:
                continue
            v = to_float(r[col])
            if v is None:
                continue
            zid = madrid_zone_id(cudis[5:7])
            ensure_zone(conn, zid, f"Madrid · {MADRID_DISTRICTS[cudis[5:7]]}", "Madrid", "distrito")
            set_indicator(conn, zid, key, v, "SERPAVI", year, f"{col}")
            stats["distritos"] += 1
    conn.commit()
    return stats
