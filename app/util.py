"""Small shared helpers."""
from __future__ import annotations

import math
import re
import statistics
import unicodedata


def slug(text: str | None) -> str:
    if not text:
        return ""
    t = unicodedata.normalize("NFKD", str(text)).encode("ascii", "ignore").decode()
    t = re.sub(r"[^a-zA-Z0-9]+", "-", t.lower()).strip("-")
    return t


def clamp(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


def median(values):
    vals = [v for v in values if v is not None]
    return statistics.median(vals) if vals else None


def haversine_m(lat1, lon1, lat2, lon2) -> float:
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def to_float(v):
    """Parse numbers the way Spanish sources write them ('1.250,5', '250000', None)."""
    if v is None or v == "":
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip().replace("€", "").replace("m²", "").replace("m2", "").strip()
    if not s:
        return None
    if "," in s and "." in s:
        s = s.replace(".", "").replace(",", ".")
    elif "," in s:
        s = s.replace(",", ".")
    elif s.count(".") > 1:
        s = s.replace(".", "")
    try:
        return float(s)
    except ValueError:
        return None


def to_money(v):
    """Like to_float, but a lone '.' followed by exactly three digits is a thousands separator ('450.000' -> 450000).
    Only for prices: for coordinates ('40.345') that reading would be wrong, so to_float stays the default."""
    if isinstance(v, str) and re.fullmatch(r"\s*\d{1,3}\.\d{3}\s*(€)?\s*", v):
        return float(v.replace("€", "").replace(".", "").strip())
    return to_float(v)


def to_bool(v) -> bool | None:
    if v is None or v == "":
        return None
    if isinstance(v, bool):
        return v
    return str(v).strip().lower() in {"1", "true", "yes", "si", "sí", "y", "x"}
