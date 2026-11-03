"""Listing values derived from all of a listing's sightings (research R11, data-model § Extended: listings).

A pure function of the sightings, so the result does not depend on the order emails were processed.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

from . import zones

ATTRIBUTES = ("area_m2", "bedrooms", "floor", "exterior", "elevator", "garage", "property_type",
              "type_text", "location_text", "development", "unit_description")


def _instant(seen_at: str) -> datetime:
    dt = datetime.fromisoformat(seen_at)
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _day(seen_at: str) -> str:
    return seen_at[:10]  # the alert's own local date, as the user saw it


USER_ORIGINS = ("manual", "csv")  # field_sources values an alert never overwrites (FR-023)
PROTECTED_COLUMNS = ("url", "title", "municipality", "district", "zone_id")  # also user-owned when their origin is
_UNITS = {"price": " €", "area_m2": " m²"}


def _date(day: str) -> str:
    return f"{day[8:10]}/{day[5:7]}/{day[:4]}"


def _show(col: str, value) -> str:
    """A value as the flags show it: 645.000 €, 150 m², sí/no, else plain text."""
    if col in ("exterior", "elevator", "garage", "new_build"):
        return "sí" if value else "no"
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    if col == "price":
        return f"{value:,}".replace(",", ".") + _UNITS[col]
    text = str(value).replace(".", ",") if isinstance(value, float) else str(value)
    return text + _UNITS.get(col, "")


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
    sources = json.loads(existing["field_sources"]) if existing is not None and existing["field_sources"] else {}
    if existing is not None:  # an alert never writes null over a known value (FR-011)
        for col in ATTRIBUTES:
            if v[col] is None and col in existing.keys():
                v[col] = existing[col]
    price, price_updated_at, history, flags = _price_rules(rows)
    if price is None and existing is not None:
        price = existing["price"]
    zone_id, municipality, district = next(  # latest location text that resolves a zone, else none
        (z for z in (zones.match_zone(r["location_text"], conn) for r in reversed(rows)) if z[0]),
        (None, None, None))
    stated_new_build = any(r["new_build_stated"] for r in rows)
    new_build, new_build_origin = (1, "email") if stated_new_build else (None, None)
    if existing is not None and (existing["new_build_origin"] == "user" or not stated_new_build):
        new_build, new_build_origin = existing["new_build"], existing["new_build_origin"]
    new_listing_days = [_day(r["seen_at"]) for r in rows if r["alert_type"] == "new_listing"]
    title = " en ".join(t for t in (v["type_text"], v["location_text"]) if t) or None

    values = {
        "source": "idealista", "url": _latest(rows, "link_direct"), "title": title,
        "property_type": v["property_type"], "price": price,
        "area_m2": v["area_m2"], "bedrooms": v["bedrooms"], "floor": v["floor"],
        "exterior": v["exterior"], "elevator": v["elevator"], "garage": v["garage"],
        "new_build": new_build, "new_build_origin": new_build_origin,
        "municipality": municipality, "district": district, "zone_id": zone_id,
        "location_text": v["location_text"], "development": v["development"],
        "unit_description": v["unit_description"],
        "first_seen": _day(rows[0]["seen_at"]), "last_seen": _day(rows[-1]["seen_at"]),
        "published_at": min(new_listing_days) if new_listing_days else None,
        "price_updated_at": price_updated_at,
    }
    price_owned = existing is not None and existing["price"] is not None and sources.get("price") in USER_ORIGINS
    nb_owned = existing is not None and existing["new_build"] is not None and (
        existing["new_build_origin"] == "user" or sources.get("new_build") in USER_ORIGINS)
    if nb_owned:  # a user's new-build value is kept; an alert stating otherwise is flagged (FR-023). An API value is not user-owned: an email's statement wins (data-model)
        values["new_build"], values["new_build_origin"] = existing["new_build"], existing["new_build_origin"]
        latest = next((r for r in reversed(rows) if r["new_build_stated"]), None)
        if latest is not None and existing["new_build"] != 1:
            flags.append(f"la alerta dice {_show('new_build', 1)} ({_date(_day(latest['seen_at']))})")
    if existing is not None:
        # an alert never writes null over a known value (FR-011); the zone trio moves together
        kept_ids = {col for col in ("url", "title") if existing[col] is not None
                    and sources.get(col) not in (None, "alert")}  # user or API value (legacy/alert ones are re-derived)
        for col in ("url", "title"):
            if col in kept_ids or values[col] is None:
                values[col] = existing[col]
        if zone_id is None:
            values["municipality"], values["district"], values["zone_id"] = (
                existing["municipality"], existing["district"], existing["zone_id"])
        # a value the user entered is never written; a differing alert value is flagged instead (FR-023)
        def protected(col):
            return existing[col] is not None and sources.get(col) in USER_ORIGINS
        for col in ("price", *ATTRIBUTES):
            if col in values and protected(col):
                latest = next((r for r in reversed(rows) if r[col] is not None), None)
                alert_value = _alert_price(rows) if col == "price" else latest[col] if latest else None
                if latest is not None and alert_value != existing[col]:
                    flags.append(f"la alerta dice {_show(col, alert_value)} ({_date(_day(latest['seen_at']))})")
                values[col] = existing[col]
        for col in PROTECTED_COLUMNS:
            if protected(col):
                values[col] = existing[col]
        if protected("municipality"):  # zone follows the user's municipality, not the alert's location text
            values["district"], values["zone_id"] = existing["district"], existing["zone_id"]
    if price_owned:  # no alert changed the listing's price: no updated date, no alert price series (FR-007, FR-036)
        values["price_updated_at"], history = existing["price_updated_at"], []
    stated = {"price": _alert_price(rows), "url": _latest(rows, "link_direct"), "title": title,
              "new_build": 1 if stated_new_build and not nb_owned else None,
              "municipality": municipality, "district": district, "zone_id": zone_id,
              **{col: _latest(rows, col) for col in ATTRIBUTES}}
    for col in kept_ids if existing is not None else ():
        stated.pop(col)
    if existing is not None and protected("municipality"):  # the user's zone is never labelled 'alert', whatever the sightings say
        stated.pop("district"), stated.pop("zone_id")
    for col, alert_value in stated.items():  # 'alert' only where an alert supplied the stored value
        if alert_value is not None and values.get(col) == alert_value and sources.get(col) not in USER_ORIGINS:
            sources[col] = "alert"
    for col, value in values.items():  # a field left null has no origin
        if value is None:
            sources.pop(col, None)
    values["field_sources"] = json.dumps(sources, sort_keys=True)
    # Relisted (FR-019): a gone listing seen in an alert on a local day after the day it was marked. Rebuilt on every
    # derivation from the sightings plus the user's mark, so it never depends on processing order; availability itself
    # is never written here. A sighting on the same day as the mark is not "later" (it may predate the mark).
    if existing is not None and existing["availability"] == "gone" and existing["availability_changed_at"]:
        later = [_day(r["seen_at"]) for r in rows if _day(r["seen_at"]) > existing["availability_changed_at"][:10]]
        if later:
            flags.append(f"vuelto a ver en una alerta el {_date(max(later))}")
    values["alert_flags"] = json.dumps(flags, ensure_ascii=False)
    if existing is None:
        cols = ["id", *values]
        conn.execute(f"INSERT INTO listings({','.join(cols)}) VALUES({','.join('?' * len(cols))})",
                     [listing_id, *values.values()])
    else:
        conn.execute(f"UPDATE listings SET {','.join(f'{c}=?' for c in values)} WHERE id=?",
                     [*values.values(), listing_id])
    _write_price_history(conn, listing_id, history)


def _day_prices(rows) -> dict:
    """day -> prices stated that day (null prices ignored), days in order."""
    days: dict = {}
    for r in rows:
        if r["price"] is not None:
            days.setdefault(_day(r["seen_at"]), []).append(r["price"])
    return dict(sorted(days.items()))


def _alert_price(rows):
    """The current alert price: the latest day's price, the higher one if that day has two (R11)."""
    days = _day_prices(rows)
    return max(days[max(days)]) if days else None


def _price_rules(rows):
    """(current price, price_updated_at, history rows, flags) from the sightings alone (R11, FR-035).

    History rows are (day, price, origin, email_id): one `alert` row per day whose price differs from the
    previous one, and an `alert_previous` row per price drop, dated the same day and listed first."""
    days = _day_prices(rows)
    flags, history, updated = [], [], None
    previous = None  # price in force after the last processed day
    for day, prices in days.items():
        day_rows = [r for r in rows if _day(r["seen_at"]) == day]
        price = max(prices)
        if len(set(prices)) > 1:
            flags.append(f"precios en conflicto el {_date(day)}")
        drops = [r for r in day_rows if r["alert_type"] == "price_drop" and r["previous_price"] is not None]
        for r in drops:
            if previous is not None and r["previous_price"] != previous:
                flags.append(f"la alerta dice precio anterior {_show('price', r['previous_price'])}, "
                             f"registrado {_show('price', previous)}")
            history.append((day, r["previous_price"], "alert_previous", r["email_id"]))
        shown = drops[-1]["previous_price"] if drops else previous
        if price != shown:
            email_id = min(r["email_id"] for r in day_rows if r["price"] == price)
            history.append((day, price, "alert", email_id))
        if price != previous and (previous is not None or any(r["alert_type"] == "price_drop" for r in day_rows)):
            updated = day
        previous = price
    return (previous, updated, history, flags)


def _write_price_history(conn, listing_id: str, history) -> None:
    """Rebuild the alert rows of the price history; rows of other origins are left alone."""
    conn.execute("DELETE FROM price_history WHERE listing_id=? AND origin IN ('alert','alert_previous')",
                 (listing_id,))
    for day, price, origin, email_id in history:
        conn.execute("INSERT INTO price_history(listing_id,day,price,origin,email_id) VALUES(?,?,?,?,?)",
                     (listing_id, day, price, origin, email_id))
