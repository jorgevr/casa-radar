"""Zone recognition from a listing's location text (research R10). Never guesses: no match -> None."""
from __future__ import annotations

import csv
import re
from functools import lru_cache

import yaml

from .db import ROOT, ensure_zone
from .etl.indicators import MADRID_DISTRICTS
from .util import slug

MUNICIPALITIES_PATH = ROOT / "config" / "zones_madrid_region.csv"
ALIASES_PATH = ROOT / "config" / "zone_aliases.yaml"
NOT_RECOGNISED = (None, None, None)

_ARTICLE_SUFFIX = re.compile(r"^(?P<name>.+), (?P<article>El|La|Los|Las)$")


@lru_cache(maxsize=1)
def municipalities() -> dict[str, str]:
    """slug -> name in reading order. INE writes "Rozas de Madrid, Las"; listings say "Las Rozas de Madrid"."""
    out = {}
    with open(MUNICIPALITIES_PATH, encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            name = row["municipality"].strip()
            m = _ARTICLE_SUFFIX.match(name)
            if m:
                name = f"{m['article']} {m['name']}"
            out[slug(name)] = name
    return out


def districts() -> dict[str, str]:
    return {slug(name): name for name in MADRID_DISTRICTS.values()}


def aliases() -> dict[str, str]:
    if not ALIASES_PATH.exists():
        return {}
    with open(ALIASES_PATH, encoding="utf-8") as f:
        return {str(k): str(v) for k, v in (yaml.safe_load(f) or {}).items()}


def _from_zone_id(zone_id: str):
    muni, _, district = zone_id.partition("/")
    if district:
        return zone_id, municipalities().get(muni), districts().get(district)
    return zone_id, municipalities().get(muni), None


def match_zone(location_text: str | None, conn=None) -> tuple[str | None, str | None, str | None]:
    """(zone_id, municipality, district). With `conn`, the zone row is created if missing."""
    if not location_text:
        return NOT_RECOGNISED
    alias = aliases().get(location_text.strip())
    if alias:
        result = _from_zone_id(alias)
    else:
        result = _match(location_text)
    if conn is not None and result[0]:
        zone_id, muni, district = result
        if district:
            ensure_zone(conn, zone_id, f"{muni} · {district}", muni, "distrito")
        else:
            ensure_zone(conn, zone_id, muni, muni, "municipio")
    return result


def _match(text: str):
    segments = [slug(s) for s in text.split(",")]
    named = {s for s in segments if s in municipalities()}
    last = segments[-1]
    if last not in municipalities() or len(named) > 1:
        return NOT_RECOGNISED
    if last == "madrid":
        district = districts().get(segments[-2]) if len(segments) > 1 else None
        if not district:
            return NOT_RECOGNISED
        return f"madrid/{segments[-2]}", "Madrid", district
    return last, municipalities()[last], None
