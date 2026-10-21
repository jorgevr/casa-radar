"""Thin client for the Ayuntamiento de Madrid CKAN datastore (datos.madrid.es).

Behaviour taken from the catalog fiche `ayuntamiento-madrid-datos-abiertos` (verified there 2026-10-01):
  * datastore_search needs `filters` as a JSON string and every value as TEXT ({"COD_DISTRITO": "21"});
  * every field comes back as text, convert locally;
  * Akamai answers an occasional 403 to single requests — retry after a pause;
  * datastore_search_sql is blocked; don't use it.
  * Padrón: resource 200076-2-padron-csv (241k rows); COD_DIST_SECCION 2062 = district 2, section 062.
I have not run it against the live site (not reachable from my build sandbox), so field names for the
indicators you want from the padrón must be checked on first use: call `fields()` and look.
"""
from __future__ import annotations

import json
import time

import httpx

BASE = "https://datos.madrid.es/api/3/action"
UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) casa-radar/0.1", "Accept": "application/json"}


def _get(client: httpx.Client, path: str, params: dict, retries: int = 4) -> dict:
    for attempt in range(retries):
        r = client.get(f"{BASE}/{path}", params=params, headers=UA)
        if r.status_code == 403 and attempt < retries - 1:
            time.sleep(3 * (attempt + 1))
            continue
        r.raise_for_status()
        body = r.json()
        if not body.get("success"):
            raise RuntimeError(f"CKAN error: {body.get('error')}")
        return body["result"]
    raise RuntimeError("unreachable")


def fields(resource_id: str, client: httpx.Client | None = None) -> list[str]:
    c = client or httpx.Client(timeout=60)
    res = _get(c, "datastore_search", {"resource_id": resource_id, "limit": 1})
    return [f["id"] for f in res["fields"]]


def rows(resource_id: str, filters: dict | None = None, page: int = 5000, client: httpx.Client | None = None):
    c = client or httpx.Client(timeout=120)
    offset = 0
    while True:
        params = {"resource_id": resource_id, "limit": page, "offset": offset}
        if filters:
            params["filters"] = json.dumps({k: str(v) for k, v in filters.items()})
        res = _get(c, "datastore_search", params)
        recs = res["records"]
        yield from recs
        offset += len(recs)
        if not recs or offset >= int(res.get("total", 0)):
            return
        time.sleep(1.0)
