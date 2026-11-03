"""Alert categories ("found via"), research R12, FR-031/FR-032.

Rules live in config/alert_categories.yaml: a YAML list of `{contains, category}`. An alert gets the category of the
rule whose `contains` text is found in the alert's search name (or subject), comparing slug() forms so case and
accents do not matter. No match, or matches of two different categories, gives "unknown" (Article I: nothing guessed).
"""
from __future__ import annotations

import json
import os

import yaml

from . import derive
from .db import ROOT
from .util import slug

CATEGORIES_PATH = ROOT / "config" / "alert_categories.yaml"  # read at call time, like zones.ALIASES_PATH
UNKNOWN = "unknown"


def load_rules() -> list[dict]:
    """The rules as written: a list of {"contains": str, "category": str}. A missing, empty or comment-only file is
    no rules. Anything else malformed raises one ValueError naming the file (and the entry), never a silent drop."""
    if not CATEGORIES_PATH.exists():
        return []
    where = str(CATEGORIES_PATH)
    try:
        with open(CATEGORIES_PATH, encoding="utf-8") as f:
            data = yaml.safe_load(f)
    except UnicodeDecodeError as exc:
        raise ValueError(f"{where}: the file is not valid UTF-8 ({exc.reason} at byte {exc.start})") from exc
    except yaml.YAMLError as exc:
        raise ValueError(f"{where}: invalid YAML: {exc}") from exc
    if data is None:
        return []
    return validate_rules(data, where)


def validate_rules(data, where: str = "rules") -> list[dict]:
    """Strict check shared by the file loader and PUT /api/categories; ValueError on the first problem."""
    if not isinstance(data, list):
        raise ValueError(f"{where}: must be a list of {{contains, category}}, found {type(data).__name__}")
    rules = []
    for i, entry in enumerate(data, start=1):
        if not isinstance(entry, dict):
            raise ValueError(f"{where}: entry {i} must be a mapping with contains and category, "
                             f"found {type(entry).__name__}")
        for key in ("contains", "category"):
            value = entry.get(key)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{where}: entry {i}: '{key}' must be a non-empty string"
                                 f"{' (missing)' if key not in entry else ''}")
        rules.append({"contains": entry["contains"], "category": entry["category"]})
    return rules


def save_rules(rules: list[dict]) -> None:
    """Atomic: write a temp file next to the target, then replace it, so a failure never leaves a half-written file."""
    CATEGORIES_PATH.parent.mkdir(parents=True, exist_ok=True)
    data = [{"contains": r["contains"], "category": r["category"]} for r in rules]
    tmp = CATEGORIES_PATH.with_name(CATEGORIES_PATH.name + ".tmp")
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            yaml.safe_dump(data, f, allow_unicode=True, sort_keys=False)
        os.replace(tmp, CATEGORIES_PATH)
    finally:
        if tmp.exists():
            tmp.unlink()


def categorise(text: str | None, rules: list[dict] | None = None) -> tuple[str, list[str]]:
    """(category, matched_rules): `matched_rules` are the matching rules' `contains` texts as written, in file order.
    `rules` defaults to the file's rules (a ValueError if the file is malformed)."""
    rules = load_rules() if rules is None else rules
    haystack = slug(text)
    if not haystack:
        return UNKNOWN, []
    matched = [r for r in rules if slug(r["contains"]) and slug(r["contains"]) in haystack]
    categories = {r["category"] for r in matched}
    texts = [r["contains"] for r in matched]
    return (next(iter(categories)) if len(categories) == 1 else UNKNOWN), texts


def email_text(search_name: str | None, subject: str | None) -> str | None:
    """What the rules are matched against: the search name (R9), else the whole subject."""
    return search_name or subject


def recategorise_all(conn) -> None:
    """Re-derive the category of every stored email from the current rules, copy it to the sightings and
    re-derive the affected listings (FR-031). Commits at the end (one transaction), unlike derive_listing:
    this is a whole-database operation whose callers (PUT /api/categories, CLI) have nothing else to commit."""
    rules = load_rules()  # validated before any write: a malformed file leaves the database untouched
    with conn:
        affected: set[str] = set()
        for e in conn.execute("SELECT email_id, search_name, subject, category, category_rules_matched "
                              "FROM alert_emails").fetchall():
            category, matched = categorise(email_text(e["search_name"], e["subject"]), rules)
            rules_json = json.dumps(matched, ensure_ascii=False)
            conn.execute("UPDATE alert_emails SET category=?, category_rules_matched=? WHERE email_id=?",
                         (category, rules_json, e["email_id"]))
            for s in conn.execute("SELECT rowid AS rid, listing_id, category FROM sightings WHERE email_id=?",
                                  (e["email_id"],)).fetchall():
                if s["category"] != category:
                    conn.execute("UPDATE sightings SET category=? WHERE rowid=?", (category, s["rid"]))
                affected.add(s["listing_id"])
        for lid in sorted(affected):
            derive.derive_listing(conn, lid)
