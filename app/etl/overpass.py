"""Per-listing amenities from OpenStreetMap (Overpass API).

This is *not* one of the sources you listed: your public-data catalog has nothing point-based for
"how far is the park / school / station". OSM does, for free. Results are cached per listing in SQLite.
Be polite with the public endpoint: one listing per call, no bulk loops without a sleep.
"""
from __future__ import annotations

import json
import time

import httpx

from ..db import dumps, today
from ..util import haversine_m

OVERPASS_URL = "https://overpass-api.de/api/interpreter"

# category -> (overpass selector, search radius in metres)
CATEGORIES = {
    "park": ('[leisure=park]', 1500),
    "school": ('[amenity~"^(school|kindergarten)$"]', 2000),
    "health": ('[amenity~"^(hospital|clinic|doctors)$"]', 3000),
    "transit": ('[railway~"^(station|subway_entrance|tram_stop)$"]', 3000),
    "supermarket": ('[shop=supermarket]', 2000),
}


def build_query(lat: float, lon: float) -> str:
    parts = [f"nwr(around:{r},{lat},{lon}){sel};" for sel, r in CATEGORIES.values()]
    return "[out:json][timeout:40];(" + "".join(parts) + ");out center tags;"


def classify(tags: dict) -> list[str]:
    cats = []
    if tags.get("leisure") == "park":
        cats.append("park")
    if tags.get("amenity") in {"school", "kindergarten"}:
        cats.append("school")
    if tags.get("amenity") in {"hospital", "clinic", "doctors"}:
        cats.append("health")
    if tags.get("railway") in {"station", "subway_entrance", "tram_stop"}:
        cats.append("transit")
    if tags.get("shop") == "supermarket":
        cats.append("supermarket")
    return cats


def summarise(elements: list[dict], lat: float, lon: float) -> dict:
    out = {c: {"nearest_m": None, "count": 0, "nearest_name": None} for c in CATEGORIES}
    for el in elements:
        elat = el.get("lat") or (el.get("center") or {}).get("lat")
        elon = el.get("lon") or (el.get("center") or {}).get("lon")
        if elat is None or elon is None:
            continue
        d = haversine_m(lat, lon, elat, elon)
        for cat in classify(el.get("tags") or {}):
            if d > CATEGORIES[cat][1]:
                continue
            o = out[cat]
            o["count"] += 1
            if o["nearest_m"] is None or d < o["nearest_m"]:
                o["nearest_m"], o["nearest_name"] = round(d), (el.get("tags") or {}).get("name")
    return out


def fetch(lat: float, lon: float, client: httpx.Client | None = None) -> dict:
    c = client or httpx.Client(timeout=60, headers={"User-Agent": "casa-radar/0.1 (personal research)"})
    r = c.post(OVERPASS_URL, data={"data": build_query(lat, lon)})
    r.raise_for_status()
    return summarise(r.json().get("elements", []), lat, lon)


def refresh_listing(conn, listing_id: str, client: httpx.Client | None = None) -> dict:
    row = conn.execute("SELECT lat,lon FROM listings WHERE id=?", (listing_id,)).fetchone()
    if not row or row["lat"] is None or row["lon"] is None:
        raise ValueError("el anuncio no tiene coordenadas (lat/lon)")
    data = fetch(row["lat"], row["lon"], client)
    conn.execute("INSERT INTO amenities(listing_id,data,fetched) VALUES(?,?,?) "
                 "ON CONFLICT(listing_id) DO UPDATE SET data=excluded.data, fetched=excluded.fetched",
                 (listing_id, dumps(data), today()))
    conn.commit()
    time.sleep(1.0)
    return data
