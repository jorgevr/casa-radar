"""Neighbourhood score, listing opportunity score and the red-flag list.

Design rules:
- Missing data is never silently scored as "average". A component without data is dropped, the remaining
  weights are renormalised, and `coverage` tells you how much of the score was actually backed by data.
- Hard filters (your needs) don't hide listings; they mark them `excluded` with the reasons.
"""
from __future__ import annotations

import json

from . import mortgage
from .db import indicators_by_zone
from .listings import type_group
from .util import clamp, median


# ── neighbourhood ────────────────────────────────────────────────────────────
def _percentiles(values: dict[str, float]) -> dict[str, float]:
    items = sorted(values.items(), key=lambda kv: kv[1])
    n = len(items)
    if n == 1:
        return {items[0][0]: 0.5}
    out, i = {}, 0
    while i < n:  # ties share the average rank
        j = i
        while j + 1 < n and items[j + 1][1] == items[i][1]:
            j += 1
        for k in range(i, j + 1):
            out[items[k][0]] = ((i + j) / 2) / (n - 1)
        i = j + 1
    return out


def neighbourhood_scores(ind: dict[str, dict[str, float]], cfg: dict) -> dict[str, dict]:
    """zone_id -> {score 0..1 | None, parts{key: pct}, coverage}. Percentile rank across the zones you have."""
    specs = {k: v for k, v in (cfg.get("neighbourhood", {}).get("indicators") or {}).items() if v.get("weight", 0) > 0}
    ranks: dict[str, dict[str, float]] = {}
    for key, spec in specs.items():
        vals = {z: d[key] for z, d in ind.items() if key in d}
        if len(vals) < 2:
            continue  # a percentile across fewer than two zones means nothing
        pr = _percentiles(vals)
        for z, p in pr.items():
            ranks.setdefault(z, {})[key] = p if spec.get("direction", "higher") == "higher" else 1 - p
    out = {}
    total_w = sum(s["weight"] for s in specs.values()) or 1
    for z in ind:
        parts = ranks.get(z, {})
        w = sum(specs[k]["weight"] for k in parts)
        out[z] = {
            "score": sum(specs[k]["weight"] * p for k, p in parts.items()) / w if w else None,
            "parts": parts,
            "coverage": w / total_w,
        }
    return out


# ── amenities ────────────────────────────────────────────────────────────────
def amenity_score(data: dict | None, cfg: dict) -> tuple[float | None, dict]:
    if not data:
        return None, {}
    specs = cfg.get("amenities") or {}
    parts, num, den = {}, 0.0, 0.0
    for key, spec in specs.items():
        d = (data.get(key) or {}).get("nearest_m")
        if d is None:
            continue
        good, bad = spec["good_m"], spec["bad_m"]
        s = 1.0 if d <= good else 0.0 if d >= bad else 1 - (d - good) / (bad - good)
        parts[key] = {"nearest_m": round(d), "score": round(s, 2)}
        num += spec["weight"] * s
        den += spec["weight"]
    return (num / den if den else None), parts


# ── listing ──────────────────────────────────────────────────────────────────
def _hard_filters(l, needs) -> list[str]:
    h, f, g = needs.get("home", {}), needs.get("finance", {}), needs.get("geography", {})
    why = []
    if h.get("property_types") and l["property_type"] not in h["property_types"]:
        why.append(f"tipo {l['property_type']} fuera de tus tipos")
    if h.get("min_area_m2") and l["area_m2"] and l["area_m2"] < h["min_area_m2"]:
        why.append(f"{l['area_m2']:.0f} m² < {h['min_area_m2']}")
    if h.get("min_bedrooms") and l["bedrooms"] is not None and l["bedrooms"] < h["min_bedrooms"]:
        why.append(f"{l['bedrooms']} hab < {h['min_bedrooms']}")
    if h.get("require_garden") and l["garden"] == 0:
        why.append("sin jardín")
    if h.get("min_plot_m2") and l["plot_m2"] and l["plot_m2"] < h["min_plot_m2"]:
        why.append(f"parcela {l['plot_m2']:.0f} m² < {h['min_plot_m2']}")
    if f.get("max_price") and l["price"] and l["price"] > f["max_price"]:
        why.append(f"precio > {f['max_price']:,.0f} €")
    if g.get("allow_zones") and l["zone_id"] not in g["allow_zones"]:
        why.append("zona fuera de tu lista")
    return why


def _effective_savings(f: dict):
    s = f.get("savings")
    if s is None:
        return None
    return s + (f.get("equity_from_sale") or 0 if f.get("use_equity_from_sale") else 0)


def _price_benchmark(l, ind_zone: dict, medians: dict, needs: dict):
    """(benchmark_m2 expected for asking, label). Notary price first, then the median of your own listings."""
    grp = type_group(l["property_type"])
    markup = needs.get("market", {}).get("asking_markup", 0.0) or 0.0
    notary = ind_zone.get(f"notary_price_m2_{grp}")
    if notary:
        return notary * (1 + markup), "notarial"
    m = medians.get((l["zone_id"], grp))
    if m:
        return m, "mediana de tus anuncios"
    return None, None


def build_context(conn, needs: dict) -> dict:
    ind = indicators_by_zone(conn)
    rows = [dict(r) for r in conn.execute("SELECT * FROM listings")]
    by_zone_grp: dict[tuple, list] = {}
    for r in rows:
        if r["price"] and r["area_m2"]:
            by_zone_grp.setdefault((r["zone_id"], type_group(r["property_type"])), []).append(r["price"] / r["area_m2"])
    min_n = needs.get("market", {}).get("min_listings_for_median", 5)
    medians = {k: median(v) for k, v in by_zone_grp.items() if len(v) >= min_n}
    zones = {r["zone_id"]: dict(r) for r in conn.execute("SELECT * FROM zones")}
    return {
        "ind": ind,
        "medians": medians,
        "counts": {k: len(v) for k, v in by_zone_grp.items()},
        "zscores": neighbourhood_scores(ind, needs),
        "zones": zones,
    }


def evaluate(l: dict, ctx: dict, needs: dict, amen_data: dict | None, history: list[float]) -> dict:
    f, w = needs.get("finance", {}), (needs.get("scoring", {}).get("weights") or {})
    ind_zone = ctx["ind"].get(l["zone_id"], {})
    flags: list[str] = []
    comps: dict[str, float | None] = {}

    price_m2 = l["price"] / l["area_m2"] if l["price"] and l["area_m2"] else None
    if price_m2 is None:
        flags.append("falta precio o superficie")

    # price vs benchmark
    bench, bench_label = (None, None)
    discount = None
    if price_m2:
        bench, bench_label = _price_benchmark(l, ind_zone, ctx["medians"], needs)
    if bench:
        discount = 1 - price_m2 / bench
        comps["price"] = clamp(0.5 + discount * 2.5)
        if bench_label != "notarial":
            flags.append("sin precio notarial: comparas contra tus propios anuncios (sesgo de selección)")
    else:
        comps["price"] = None
        if price_m2:
            flags.append("sin referencia de precio para esta zona")

    # affordability
    sim = None
    savings = _effective_savings(f)
    if l["price"] and savings is not None and f.get("tin_pct") is not None:
        rates = mortgage.CostRates(**{k: v for k, v in (needs.get("costs") or {}).items()
                                      if k in mortgage.CostRates.__dataclass_fields__})
        sim = mortgage.simulate(l["price"], savings, f.get("years", 30), f["tin_pct"],
                                f.get("net_income_monthly"), bool(l["new_build"]), rates)
        if sim["savings_shortfall"] > 0:
            flags.append(f"te faltan {sim['savings_shortfall']:,.0f} € de ahorro para entrar")
        e, cap = sim["effort_ratio"], f.get("max_effort", 0.35)
        if e is not None:
            comps["affordability"] = clamp(1 - (e - 0.7 * cap) / (0.3 * cap))
            if e > cap:
                flags.append(f"esfuerzo {e:.0%} > tu techo {cap:.0%}")
            worst = sim["stress"][-1]["effort_ratio"] if sim["stress"] else None
            if worst and worst > cap and e <= cap:
                flags.append(f"si el tipo sube {sim['stress'][-1]['tin_pct'] - f['tin_pct']:.0f} pp, el esfuerzo pasa a {worst:.0%}")
        else:
            comps["affordability"] = None
            flags.append("indica tus ingresos netos para medir el esfuerzo")
    else:
        comps["affordability"] = None
        flags.append("completa ahorros y tipo en Necesidades para valorar la hipoteca")

    # neighbourhood + amenities
    zs = ctx["zscores"].get(l["zone_id"], {})
    comps["neighbourhood"] = zs.get("score")
    if zs.get("score") is None:
        flags.append("sin indicadores de barrio cargados")
    a_score, a_parts = amenity_score(amen_data, needs)
    comps["amenities"] = a_score
    if a_score is None:
        flags.append("servicios cercanos sin calcular")

    # fit (soft preferences)
    h, g = needs.get("home", {}), needs.get("geography", {})
    fit, fit_n = 0.0, 0
    if l["zone_id"] in (g.get("preferred_zones") or []):
        fit += 1; fit_n += 1
    elif g.get("preferred_zones"):
        fit_n += 1
    if h.get("min_bedrooms") and l["bedrooms"] is not None:
        fit += clamp((l["bedrooms"] - h["min_bedrooms"] + 1) / 2); fit_n += 1
    if l["garden"] is not None:
        fit += 1.0 if l["garden"] else 0.0; fit_n += 1
    comps["fit"] = fit / fit_n if fit_n else None

    # momentum: price drop since first seen
    drop = None
    if len(history) >= 2 and history[0]:
        drop = 1 - history[-1] / history[0]
        comps["momentum"] = clamp(drop / 0.10)
        if drop > 0:
            flags.append(f"bajada de precio acumulada {drop:.1%}")
    else:
        comps["momentum"] = None

    num = den = 0.0
    total_w = sum(w.values()) or 1
    for k, v in comps.items():
        if v is not None and w.get(k, 0) > 0:
            num += w[k] * v
            den += w[k]
    score = 100 * num / den if den else None

    return {
        "price_m2": price_m2,
        "benchmark_m2": bench,
        "benchmark_source": bench_label,
        "discount_vs_benchmark": discount,
        "components": comps,
        "score": score,
        "coverage": den / total_w,
        "mortgage": sim,
        "amenities": a_parts,
        "price_drop": drop,
        "flags": flags,
        "excluded": _hard_filters(l, needs),
        "zone_score": zs.get("score"),
    }


def rank(conn, needs: dict) -> list[dict]:
    ctx = build_context(conn, needs)
    amen = {r["listing_id"]: json.loads(r["data"]) for r in conn.execute("SELECT * FROM amenities")}
    hist: dict[str, list[float]] = {}
    for r in conn.execute("SELECT listing_id, price FROM price_history ORDER BY day, rowid"):
        hist.setdefault(r["listing_id"], []).append(r["price"])
    out = []
    for r in conn.execute("SELECT * FROM listings"):
        l = dict(r)
        l.pop("raw", None)
        l["eval"] = evaluate(l, ctx, needs, amen.get(l["id"]), hist.get(l["id"], []))
        l["days_seen"] = None
        out.append(l)
    out.sort(key=lambda x: (bool(x["eval"]["excluded"]), -(x["eval"]["score"] or -1)))
    return out


def zone_table(conn, needs: dict) -> list[dict]:
    ctx = build_context(conn, needs)
    markup_needed = []
    for zid, z in ctx["zones"].items():
        ind = ctx["ind"].get(zid, {})
        row = {**z, "indicators": ind, "score": ctx["zscores"].get(zid, {}).get("score"),
               "coverage": ctx["zscores"].get(zid, {}).get("coverage", 0), "listings": {}, "implied_markup": {}}
        for grp in ("flat", "house"):
            n = ctx["counts"].get((zid, grp), 0)
            med = ctx["medians"].get((zid, grp))
            row["listings"][grp] = {"n": n, "median_m2": med}
            nm = ind.get(f"notary_price_m2_{grp}")
            if med and nm:
                row["implied_markup"][grp] = med / nm - 1
        markup_needed.append(row)
    markup_needed.sort(key=lambda r: -(r["score"] if r["score"] is not None else -1))
    return markup_needed
