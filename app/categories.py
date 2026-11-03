"""Alert categories ("found via"), research R12, FR-031/FR-032.

Rules live in config/alert_categories.yaml: a YAML list of `{contains, category}`. An alert gets the category of the
rule whose `contains` text is found in the alert's search name (or subject), comparing slug() forms so case and
accents do not matter. No match, or matches of two different categories, gives "unknown" (Article I: nothing guessed).
"""
from __future__ import annotations

import json

import yaml

from . import derive
from .db import ROOT
from .util import slug

CATEGORIES_PATH = ROOT / "config" / "alert_categories.yaml"  # read at call time, like zones.ALIASES_PATH
UNKNOWN = "unknown"


def load_rules() -> list[dict]:
    """The rules as written: a list of {"contains": str, "category": str}; a missing or empty file is no rules."""
    if not CATEGORIES_PATH.exists():
        return []
    with open(CATEGORIES_PATH, encoding="utf-8") as f:
        data = yaml.safe_load(f) or []
    if not isinstance(data, list):
        raise ValueError("alert_categories.yaml must be a list of {contains, category}")
    return [{"contains": str(r["contains"]), "category": str(r["category"])}
            for r in data if isinstance(r, dict) and r.get("contains") and r.get("category")]


def save_rules(rules: list[dict]) -> None:
    CATEGORIES_PATH.parent.mkdir(parents=True, exist_ok=True)
    data = [{"contains": r["contains"], "category": r["category"]} for r in rules]
    with open(CATEGORIES_PATH, "w", encoding="utf-8") as f:
        yaml.safe_dump(data, f, allow_unicode=True, sort_keys=False)


def categorise(text: str | None) -> tuple[str, list[str]]:
    """(category, matched_rules): `matched_rules` are the matching rules' `contains` texts as written, in file order."""
    haystack = slug(text)
    if not haystack:
        return UNKNOWN, []
    matched = [r for r in load_rules() if slug(r["contains"]) and slug(r["contains"]) in haystack]
    categories = {r["category"] for r in matched}
    rules = [r["contains"] for r in matched]
    return (next(iter(categories)) if len(categories) == 1 else UNKNOWN), rules


def email_text(search_name: str | None, subject: str | None) -> str | None:
    """What the rules are matched against: the search name (R9), else the whole subject."""
    return search_name or subject


def recategorise_all(conn) -> None:
    """Re-derive the category of every stored email from the current rules, copy it to the sightings and
    re-derive the affected listings (FR-031). Commits at the end (one transaction), unlike derive_listing:
    this is a whole-database operation whose callers (PUT /api/categories, CLI) have nothing else to commit."""
    with conn:
        affected: set[str] = set()
        for e in conn.execute("SELECT email_id, search_name, subject, category, category_rules_matched "
                              "FROM alert_emails").fetchall():
            category, rules = categorise(email_text(e["search_name"], e["subject"]))
            rules_json = json.dumps(rules, ensure_ascii=False)
            conn.execute("UPDATE alert_emails SET category=?, category_rules_matched=? WHERE email_id=?",
                         (category, rules_json, e["email_id"]))
            for s in conn.execute("SELECT rowid AS rid, listing_id, category FROM sightings WHERE email_id=?",
                                  (e["email_id"],)).fetchall():
                if s["category"] != category:
                    conn.execute("UPDATE sightings SET category=? WHERE rowid=?", (category, s["rid"]))
                affected.add(s["listing_id"])
        for lid in sorted(affected):
            derive.derive_listing(conn, lid)
