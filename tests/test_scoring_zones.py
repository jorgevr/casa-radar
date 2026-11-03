"""T038 - golden test: listings without a zone never form a zone median (FR-013, Articles I and VII).

Rule under test: a listing whose location text matched no known zone has zone_id NULL. It must not be
grouped under a None zone in the medians (that would invent a "zone" out of unrelated places, Article I),
zone medians use only listings that have a zone, and the null-zone listing is flagged
`zona no reconocida: "<texto>"` with its original location_text (FR-013, data-model flag table). With
geography.allow_zones set it is flagged, not excluded (we cannot tell that it is outside the list).

Hand calculation (source: the median definition, middle value of the sorted list, applied to the
price / area figures below; not output of the code under test). All six are type chalet (house group),
area 120 m2, 4 bedrooms, min_listings_for_median set to 3 in the test.
Against needs.example.yaml no other hard filter excludes them: chalet is an allowed type, 120 >= min_area_m2 90,
4 >= min_bedrooms 4, require_garden false, min_plot_m2 and max_price null:

  zone-a   : 360000 / 120 = 3000 ; 420000 / 120 = 3500 ; 480000 / 120 = 4000  -> median 3500 EUR/m2 (n=3)
  zone NULL: 240000 / 120 = 2000 ; 264000 / 120 = 2200 ; 300000 / 120 = 2500  -> would-be median 2200 (n=3)
  Pooling all six would give (3000+3500)/2 = 3250 for a mixed bag; neither 2200 nor 3250 may appear.

Discount of the cheapest zone-a listing against its zone median: 1 - 3000/3500 = 1/7 = 0.142857...
"""
import copy

import pytest

from app import scoring

ZONE = "zona-a"
AREA = 120.0
BEDROOMS = 4  # meets home.min_bedrooms (4) in needs.example.yaml, so zones are the only filter under test
ROWS = [  # id, zone, price, location_text
    ("A1", ZONE, 360_000.0, "Zona A centro"),
    ("A2", ZONE, 420_000.0, "Zona A norte"),
    ("A3", ZONE, 480_000.0, "Zona A sur"),
    ("N1", None, 240_000.0, "Valdeperdido del Monte"),
    ("N2", None, 264_000.0, "Urbanizacion Los Sueños"),
    ("N3", None, 300_000.0, "Paraje sin nombre"),
]


def _load(conn):
    conn.execute("INSERT OR IGNORE INTO zones(zone_id,name,municipality,level) VALUES(?,?,?,?)",
                 (ZONE, ZONE, "test", "municipality"))
    for lid, zone, price, text in ROWS:
        conn.execute(
            "INSERT INTO listings(id,source,url,property_type,price,area_m2,bedrooms,zone_id,location_text)"
            " VALUES(?,?,?,?,?,?,?,?,?)",
            (lid, "alert", f"https://x.test/{lid}", "chalet", price, AREA, BEDROOMS, zone, text))
    conn.commit()


@pytest.fixture
def zneeds(needs):
    n = copy.deepcopy(needs)
    n.setdefault("market", {})["min_listings_for_median"] = 3
    n.setdefault("geography", {})["allow_zones"] = [ZONE]
    return n


def _zone_flags(row):
    return [f for f in row["eval"]["flags"] if f.startswith("zona no reconocida")]


def test_zone_less_median_golden(conn, zneeds):
    _load(conn)
    ctx = scoring.build_context(conn, zneeds)

    # no median or count is keyed by a None zone; only the zone with a zone_id has a median
    assert all(k[0] is not None for k in ctx["medians"])
    assert all(k[0] is not None for k in ctx["counts"])
    assert ctx["medians"] == {(ZONE, "house"): pytest.approx(3500.0)}
    assert ctx["counts"] == {(ZONE, "house"): 3}

    ranked = {r["id"]: r for r in scoring.rank(conn, zneeds)}

    # zone-a listings are scored against the 3500 median and are not flagged or excluded
    a1 = ranked["A1"]["eval"]
    assert a1["benchmark_m2"] == pytest.approx(3500.0)
    assert a1["discount_vs_benchmark"] == pytest.approx(1 / 7)
    for lid in ("A1", "A2", "A3"):
        assert _zone_flags(ranked[lid]) == []
        assert ranked[lid]["eval"]["excluded"] == []

    # null-zone listings: no benchmark from a None-zone median, flagged with their own text, not excluded
    for lid, _, _, text in ROWS[3:]:
        ev = ranked[lid]["eval"]
        assert ev["benchmark_m2"] is None
        assert ev["discount_vs_benchmark"] is None
        assert _zone_flags(ranked[lid]) == [f'zona no reconocida: "{text}"']
        assert not any("zona fuera de tu lista" in e for e in ev["excluded"])
