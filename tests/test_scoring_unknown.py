"""T037 golden test (Article I and VII): a hard filter on an unknown field flags, never passes silently, never excludes.

Rules under test (spec FR-012 and FR-013; data-model.md "Flag texts"; Article I "no imputed values"):
- FR-012: "Hard filters on an unknown field MUST flag the listing, neither passing nor excluding it."
- data-model "Flag texts", row "unknown field on a hard filter", exact strings:
    min_area_m2 -> "superficie desconocida"      min_bedrooms -> "habitaciones desconocidas"
    require_garden -> "jardín desconocido"       min_plot_m2 -> "parcela desconocida"
    max_price -> "precio desconocido"
- FR-013 + row "zone not recognised": a listing whose zone is null (zone_id NULL) gets the flag
  `zona no reconocida: "<texto>"` with the original location text, and allow_zones flags it, not excludes it.
- Known values behave as before (the existing reasons in app/scoring.py and tests/test_core.py).

Hand reasoning (no expected value comes from running the code). Filters set by hand in `filtered_needs`:
  min_area_m2 90, min_bedrooms 4, require_garden true, min_plot_m2 200, max_price 500.000, allow_zones [zona-a].
  A listing with area 100, 4 bedrooms, garden 1, plot 300, price 400.000, zone zona-a satisfies every filter
  (100 >= 90, 4 >= 4, garden present, 300 >= 200, 400.000 <= 500.000, zone listed) -> excluded == [], no flags.
  Setting exactly one field to NULL leaves the other five satisfied, so the only possible effects come from the
  null: it must produce exactly its one flag from the table above and `excluded` must stay empty.
  Known failing values (area 80 < 90, 3 bedrooms < 4, garden 0, plot 150 < 200, price 600.000 > 500.000,
  zone zona-b not in [zona-a]) must still exclude, and must NOT add an "desconocido" flag, because the field is known.
"""
import subprocess
from pathlib import Path

import pytest

from app import scoring

ROOT = Path(__file__).resolve().parent.parent

GOOD = {"area_m2": 100.0, "bedrooms": 4, "garden": 1, "plot_m2": 300.0, "price": 400_000.0, "zone_id": "zona-a"}

# field -> exact flag text from data-model "Flag texts" (row: unknown field on a hard filter)
UNKNOWN_FLAG = {
    "area_m2": "superficie desconocida",
    "bedrooms": "habitaciones desconocidas",
    "garden": "jardín desconocido",
    "plot_m2": "parcela desconocida",
    "price": "precio desconocido",
}
ALL_UNKNOWN_FLAGS = set(UNKNOWN_FLAG.values())


@pytest.fixture
def filtered_needs(needs):
    n = dict(needs)
    n["home"] = {**needs["home"], "property_types": ["chalet"], "min_area_m2": 90, "min_bedrooms": 4,
                 "require_garden": True, "min_plot_m2": 200}
    n["finance"] = {**needs["finance"], "max_price": 500_000}
    n["geography"] = {**needs.get("geography", {}), "allow_zones": ["zona-a"]}
    return n


def _put(conn, lid, location_text="Getafe", **over):
    v = {**GOOD, **over}
    for z in ("zona-a", "zona-b"):
        conn.execute("INSERT OR IGNORE INTO zones(zone_id,name,municipality,level) VALUES(?,?,?,?)",
                     (z, z, "test", "municipality"))
    conn.execute(
        "INSERT INTO listings(id,source,url,property_type,price,area_m2,bedrooms,garden,plot_m2,zone_id,location_text)"
        " VALUES(?,?,?,?,?,?,?,?,?,?,?)",
        (lid, "alert", f"https://x.test/{lid}", "chalet", v["price"], v["area_m2"], v["bedrooms"], v["garden"],
         v["plot_m2"], v["zone_id"], location_text))
    conn.commit()
    return lid


def _ev(conn, needs, lid):
    return {r["id"]: r for r in scoring.rank(conn, needs)}[lid]["eval"]


def test_unknown_fields_golden(conn, filtered_needs):
    # --- baseline: every filter satisfied by a known value -> no exclusion, no unknown/zone flag ----------
    _put(conn, "ok")
    ev = _ev(conn, filtered_needs, "ok")
    assert ev["excluded"] == []
    assert not [f for f in ev["flags"] if "desconocid" in f or "zona no reconocida" in f]

    # --- each filtered field null on its own: exactly its flag (FR-012), and no exclusion ------------------
    for field, text in UNKNOWN_FLAG.items():
        lid = _put(conn, f"null-{field}", **{field: None})
        ev = _ev(conn, filtered_needs, lid)
        assert ev["excluded"] == [], f"{field}: unknown must not exclude"
        assert text in ev["flags"], f"{field}: missing flag {text!r}"
        others = ALL_UNKNOWN_FLAGS - {text}
        assert not others & set(ev["flags"]), f"{field}: only its own unknown flag"

    # --- allow_zones with a null zone: zone-not-recognised flag with the original text (FR-013), no exclusion
    _put(conn, "null-zone", location_text="Urbanización Los Pinos", zone_id=None)
    ev = _ev(conn, filtered_needs, "null-zone")
    assert ev["excluded"] == []
    assert 'zona no reconocida: "Urbanización Los Pinos"' in ev["flags"]
    assert "zona fuera de tu lista" not in ev["excluded"]


def test_known_values_still_exclude(conn, filtered_needs):
    # known values below/above the limit behave as before and raise no "desconocido" flag (field is known)
    cases = {
        "area_m2": 80.0,       # 80 < 90
        "bedrooms": 3,         # 3 < 4
        "garden": 0,           # require_garden, garden known to be 0
        "plot_m2": 150.0,      # 150 < 200
        "price": 600_000.0,    # 600.000 > 500.000
        "zone_id": "zona-b",   # known zone not in allow_zones [zona-a]
    }
    for field, bad in cases.items():
        lid = _put(conn, f"bad-{field}", **{field: bad})
        ev = _ev(conn, filtered_needs, lid)
        assert len(ev["excluded"]) == 1, f"{field}: known failing value must exclude exactly once"
        assert not ALL_UNKNOWN_FLAGS & set(ev["flags"])
        assert not [f for f in ev["flags"] if "zona no reconocida" in f]


def test_existing_core_tests_untouched():
    """T037: tests/test_core.py expectations must not change (git diff against the branch point is empty)."""
    def git(*a):
        return subprocess.run(["git", *a], cwd=ROOT, capture_output=True, text=True)
    base = git("merge-base", "HEAD", "jorgevr/spec-kit-3-feature")
    if base.returncode != 0:
        pytest.skip("branch point not available")
    diff = git("diff", base.stdout.strip(), "--", "tests/test_core.py")
    assert diff.returncode == 0 and diff.stdout == ""
