"""Listing values derived from all of a listing's sightings (research R11, data-model § Extended: listings).

A pure function of the sightings, so the result does not depend on the order emails were processed.
"""
from __future__ import annotations

from datetime import datetime, timezone

from . import zones

ATTRIBUTES = ("area_m2", "bedrooms", "floor", "exterior", "elevator", "garage", "property_type",
              "type_text", "location_text", "development", "unit_description")


def _instant(seen_at: str) -> datetime:
    dt = datetime.fromisoformat(seen_at)
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _day(seen_at: str) -> str:
    return seen_at[:10]  # the alert's own local date, as the user saw it


def sightings(conn, listing_id: str) -> list:
    rows = conn.execute("SELECT * FROM sightings WHERE listing_id=?", (listing_id,)).fetchall()
    return sorted(rows, key=lambda r: (_instant(r["seen_at"]), r["email_id"]))


def _latest(rows, col):
    return next((r[col] for r in reversed(rows) if r[col] is not None), None)


def derive_listing(conn, listing_id: str) -> None:
    """Insert or update the listing from its sightings and rebuild its alert price history.
    Does not commit: the caller owns the transaction."""
    rows = sightings(conn, listing_id)
    if not rows:
        return
    existing = conn.execute("SELECT * FROM listings WHERE id=?", (listing_id,)).fetchone()
    v = {col: _latest(rows, col) for col in ATTRIBUTES}
    if existing is not None:  # an alert never writes null over a known value (FR-011)
        for col in ATTRIBUTES:
            if v[col] is None and col in existing.keys():
                v[col] = existing[col]
    zone_id, municipality, district = zones.match_zone(v["location_text"], conn)
    stated_new_build = any(r["new_build_stated"] for r in rows)
    new_build, new_build_origin = (1, "email") if stated_new_build else (None, None)
    if existing is not None and (existing["new_build_origin"] == "user" or not stated_new_build):
        new_build, new_build_origin = existing["new_build"], existing["new_build_origin"]
    new_listing_days = [_day(r["seen_at"]) for r in rows if r["alert_type"] == "new_listing"]
    title = " en ".join(t for t in (v["type_text"], v["location_text"]) if t) or None

    values = {
        "source": "idealista", "url": rows[-1]["link_direct"], "title": title,
        "property_type": v["property_type"], "price": rows[-1]["price"],
        "area_m2": v["area_m2"], "bedrooms": v["bedrooms"], "floor": v["floor"],
        "exterior": v["exterior"], "elevator": v["elevator"], "garage": v["garage"],
        "new_build": new_build, "new_build_origin": new_build_origin,
        "municipality": municipality, "district": district, "zone_id": zone_id,
        "location_text": v["location_text"], "development": v["development"],
        "unit_description": v["unit_description"],
        "first_seen": _day(rows[0]["seen_at"]), "last_seen": _day(rows[-1]["seen_at"]),
        "published_at": min(new_listing_days) if new_listing_days else None,
    }
    if existing is None:
        cols = ["id", *values]
        conn.execute(f"INSERT INTO listings({','.join(cols)}) VALUES({','.join('?' * len(cols))})",
                     [listing_id, *values.values()])
    else:
        conn.execute(f"UPDATE listings SET {','.join(f'{c}=?' for c in values)} WHERE id=?",
                     [*values.values(), listing_id])
    _rebuild_price_history(conn, listing_id, rows)


def _rebuild_price_history(conn, listing_id: str, rows) -> None:
    """One `alert` row per price change; a price drop's stated previous price goes first, same day."""
    conn.execute("DELETE FROM price_history WHERE listing_id=? AND origin IN ('alert','alert_previous')",
                 (listing_id,))
    previous = None
    for r in rows:
        day = _day(r["seen_at"])
        if r["alert_type"] == "price_drop" and r["previous_price"] is not None:
            conn.execute("INSERT INTO price_history(listing_id,day,price,origin,email_id) VALUES(?,?,?,?,?)",
                         (listing_id, day, r["previous_price"], "alert_previous", r["email_id"]))
            previous = r["previous_price"]
        if r["price"] is not None and r["price"] != previous:
            conn.execute("INSERT INTO price_history(listing_id,day,price,origin,email_id) VALUES(?,?,?,?,?)",
                         (listing_id, day, r["price"], "alert", r["email_id"]))
            previous = r["price"]
