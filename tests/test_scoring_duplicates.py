"""T024 - golden test for possible-duplicate detection (FR-018, research R15, Article VII).

Rule under test (spec FR-018 / research R15): two listings in the same zone, with the same property type
and the same bedrooms, are flagged "posible duplicado de <id>" (each naming the other) when
|a-b|/max(a,b) <= 0.03 for area AND <= 0.05 for price, boundaries inclusive. Unknown area/price,
an unrecognised zone (zone_id NULL) or development=1 never flag.

Expected values below are hand calculations from those two sources, not output of the code under test.
Numbers are chosen so each boundary is exact in IEEE-754 doubles:
  3 / 100        == 0.03   (correctly rounded quotient equals the literal 0.03)
  20000 / 400000 == 0.05   (same)
so the inclusive boundary is not float-fragile for the straightforward |a-b|/max(a,b) <= t form.
"""
import pytest

from app import scoring

ZONE_A, ZONE_B = "zona-a", "zona-b"
BASE_AREA, BASE_PRICE = 100.0, 400_000.0


def _flags(rows, lid):
    return [f for f in rows[lid]["eval"]["flags"] if "duplicado" in f]


def _put(conn, lid, area=BASE_AREA, price=BASE_PRICE, zone=ZONE_A, ptype="piso", beds=3,
         development=0, merged_into=None):
    if zone:
        conn.execute(
            "INSERT OR IGNORE INTO zones(zone_id,name,municipality,level) VALUES(?,?,?,?)",
            (zone, zone, "test", "municipality"),
        )
    conn.execute(
        "INSERT INTO listings(id,source,url,property_type,price,area_m2,bedrooms,zone_id,development,merged_into)"
        " VALUES(?,?,?,?,?,?,?,?,?,?)",
        (lid, "alert", f"https://x.test/{lid}", ptype, price, area, beds, zone, development, merged_into),
    )
    conn.commit()
    return lid


def _rank(conn, needs):
    return {r["id"]: r for r in scoring.rank(conn, needs)}


def _pair(conn, needs, **second):
    _put(conn, "A")
    _put(conn, "B", **second)
    return _rank(conn, needs)


def test_duplicates_golden(conn, needs):
    # --- exactly 3.0 % area, exactly 5.0 % price: flagged on BOTH, inclusive boundaries ---------------
    # area  |100 - 97| / max(100, 97) = 3 / 100 = 0.03   <= 0.03 (FR-018 / R15, inclusive)
    # price |400000 - 380000| / max = 20000 / 400000 = 0.05 <= 0.05 (inclusive)
    rows = _pair(conn, needs, area=97.0, price=380_000.0)
    assert _flags(rows, "A") == ["posible duplicado de B"]
    assert _flags(rows, "B") == ["posible duplicado de A"]


def test_area_just_over_three_percent_not_flagged(conn, needs):
    # area |100 - 96.99| / 100 = 3.01 / 100 = 0.0301 > 0.03 -> not a duplicate (price diff 0 is fine)
    rows = _pair(conn, needs, area=96.99)
    assert _flags(rows, "A") == [] and _flags(rows, "B") == []


def test_price_just_over_five_percent_not_flagged(conn, needs):
    # price |400000 - 379960| / 400000 = 20040 / 400000 = 0.0501 > 0.05 -> not a duplicate
    rows = _pair(conn, needs, price=379_960.0)
    assert _flags(rows, "A") == [] and _flags(rows, "B") == []


def test_identical_values_flagged(conn, needs):
    # 0 % area and 0 % price difference are within both limits (0 <= 0.03, 0 <= 0.05)
    rows = _pair(conn, needs)
    assert _flags(rows, "A") == ["posible duplicado de B"]
    assert _flags(rows, "B") == ["posible duplicado de A"]


def test_metric_is_relative_to_the_larger_value(conn, needs):
    # Denominator is max(a,b), not min: |97 - 100| / max = 3/100 = 0.03 (flag). Dividing by the smaller
    # value would give 3/97 = 0.0309 (> 0.03, no flag). Pair is built with the smaller one first.
    _put(conn, "A", area=97.0)
    _put(conn, "B", area=100.0)
    rows = _rank(conn, needs)
    assert _flags(rows, "A") == ["posible duplicado de B"]
    assert _flags(rows, "B") == ["posible duplicado de A"]


def test_unknown_area_or_price_not_flagged(conn, needs):
    # Article I / FR-018: an unknown value is never imputed, so no comparison and no flag.
    _put(conn, "A")
    _put(conn, "B", area=None)
    _put(conn, "C", price=None)
    rows = _rank(conn, needs)
    for lid in "ABC":
        assert _flags(rows, lid) == []


def test_unrecognised_zone_not_flagged(conn, needs):
    # FR-018: "the zone is not recognised -> no flag"; two NULL zones must not count as the same zone.
    _put(conn, "A", zone=None)
    _put(conn, "B", zone=None)
    rows = _rank(conn, needs)
    assert _flags(rows, "A") == [] and _flags(rows, "B") == []


def test_development_not_flagged(conn, needs):
    # R13 / R15: developments are skipped by the duplicate check (even if the other one is not).
    rows = _pair(conn, needs, development=1)
    assert _flags(rows, "A") == [] and _flags(rows, "B") == []


@pytest.mark.parametrize("override", [{"zone": ZONE_B}, {"ptype": "atico"}, {"beds": 2}])
def test_different_zone_type_or_bedrooms_not_flagged(conn, needs, override):
    # FR-018 requires the same zone, property type and bedrooms; values otherwise identical.
    rows = _pair(conn, needs, **override)
    assert _flags(rows, "A") == [] and _flags(rows, "B") == []


def test_merged_listing_is_skipped_in_ranking(conn, needs):
    # T028 / FR-018: a listing with merged_into set is skipped (not returned as a row), and it takes
    # no part in duplicate detection: the surviving target has no partner, hence no flag.
    _put(conn, "A")
    _put(conn, "B", merged_into="A")
    rows = _rank(conn, needs)
    assert set(rows) == {"A"}
    assert _flags(rows, "A") == []
