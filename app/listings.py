"""Listing normalisation and storage. Every provider ends up calling `upsert_listing`."""
from __future__ import annotations

import hashlib

from .db import dumps, ensure_zone, today
from .util import slug, to_bool, to_float, to_money

HOUSE_TYPES = {"chalet", "adosado", "pareado", "unifamiliar", "casa"}
FLAT_TYPES = {"piso", "bajo", "atico", "duplex", "estudio", "otro"}

_TYPE_ALIASES = {
    "flat": "piso", "apartment": "piso", "piso": "piso",
    "groundfloor": "bajo", "ground_floor": "bajo", "bajo": "bajo",
    "penthouse": "atico", "atico": "atico", "ático": "atico",
    "chalet": "chalet", "villa": "chalet", "house": "chalet", "independienteviviendas": "chalet",
    "casa": "chalet", "countryhouse": "chalet", "unifamiliar": "chalet",
    "terracedhouse": "adosado", "adosado": "adosado", "semidetachedhouse": "pareado",
    "pareado": "pareado", "duplex": "duplex", "studio": "estudio",
}


def norm_type(v) -> str:
    key = slug(v).replace("-", "") if v else ""
    return _TYPE_ALIASES.get(key, key if key in HOUSE_TYPES | FLAT_TYPES else "otro")


def type_group(property_type: str) -> str:
    return "house" if property_type in HOUSE_TYPES else "flat"


def zone_for(municipality, district, needs: dict) -> tuple[str, str, str]:
    """(zone_id, display name, level). Madrid city (and others in geography.district_level) per district."""
    muni = slug(municipality) or "desconocido"
    district_level = {slug(m) for m in (needs.get("geography", {}).get("district_level") or [])}
    if muni in district_level and district:
        return f"{muni}/{slug(district)}", f"{municipality} · {district}", "distrito"
    return muni, municipality or "Desconocido", "municipio"


def listing_id(source: str, external_id, url) -> str:
    base = f"{source}:{external_id}" if external_id else f"{source}:{url}"
    return base if external_id else f"{source}:{hashlib.sha1(base.encode()).hexdigest()[:12]}"


def normalise(d: dict) -> dict:
    """Map loose keys (Spanish/English/Idealista-style) to our schema."""
    def pick(*keys):
        for k in keys:
            if k in d and d[k] not in (None, ""):
                return d[k]
        return None

    ptype = norm_type(pick("property_type", "propertyType", "tipo", "type", "subtype"))
    return {
        "external_id": pick("external_id", "propertyCode", "id", "code"),
        "url": pick("url", "link"),
        "title": pick("title", "titulo", "suggestedTexts", "description", "address"),
        "property_type": ptype,
        "price": to_money(pick("price", "precio", "priceInfo")),
        "area_m2": to_float(pick("area_m2", "size", "area", "superficie", "m2")),
        "bedrooms": (lambda v: int(v) if v is not None else None)(to_float(pick("bedrooms", "rooms", "habitaciones", "dormitorios"))),
        "bathrooms": (lambda v: int(v) if v is not None else None)(to_float(pick("bathrooms", "baños", "banos"))),
        "plot_m2": to_float(pick("plot_m2", "lotSize", "parcela")),
        "garden": to_bool(pick("garden", "jardin", "jardín", "hasGarden")),
        "new_build": to_bool(pick("new_build", "newDevelopment", "obra_nueva")),
        "lat": to_float(pick("lat", "latitude")),
        "lon": to_float(pick("lon", "lng", "longitude")),
        "municipality": pick("municipality", "municipio", "town", "city"),
        "district": pick("district", "distrito"),
        "neighborhood": pick("neighborhood", "neighbourhood", "barrio"),
    }


def upsert_listing(conn, raw: dict, source: str, needs: dict) -> str:
    n = normalise(raw)
    lid = listing_id(source, n["external_id"], n["url"] or n["title"])
    zone_id, zname, level = zone_for(n["municipality"], n["district"], needs)
    ensure_zone(conn, zone_id, zname, n["municipality"], level)
    day = today()
    existing = conn.execute("SELECT price FROM listings WHERE id=?", (lid,)).fetchone()
    if existing is None:
        conn.execute(
            "INSERT INTO listings(id,source,url,title,property_type,price,area_m2,bedrooms,bathrooms,"
            "plot_m2,garden,new_build,lat,lon,municipality,district,neighborhood,zone_id,first_seen,last_seen,raw) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (lid, source, n["url"], n["title"], n["property_type"], n["price"], n["area_m2"], n["bedrooms"],
             n["bathrooms"], n["plot_m2"], None if n["garden"] is None else int(n["garden"]),
             None if n["new_build"] is None else int(n["new_build"]), n["lat"], n["lon"], n["municipality"],
             n["district"], n["neighborhood"], zone_id, day, day, dumps(raw)),
        )
        if n["price"]:
            conn.execute("INSERT INTO price_history VALUES(?,?,?)", (lid, day, n["price"]))
    else:
        conn.execute(
            "UPDATE listings SET url=?,title=?,property_type=?,price=?,area_m2=?,bedrooms=?,bathrooms=?,plot_m2=?,"
            "garden=?,new_build=?,lat=COALESCE(?,lat),lon=COALESCE(?,lon),municipality=?,district=?,neighborhood=?,"
            "zone_id=?,last_seen=?,raw=? WHERE id=?",
            (n["url"], n["title"], n["property_type"], n["price"], n["area_m2"], n["bedrooms"], n["bathrooms"],
             n["plot_m2"], None if n["garden"] is None else int(n["garden"]),
             None if n["new_build"] is None else int(n["new_build"]), n["lat"], n["lon"], n["municipality"],
             n["district"], n["neighborhood"], zone_id, day, dumps(raw), lid),
        )
        if n["price"] and n["price"] != existing["price"]:
            conn.execute("INSERT INTO price_history VALUES(?,?,?)", (lid, day, n["price"]))
    conn.commit()
    return lid
