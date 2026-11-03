"""T028 regression tests for the review findings (Article VII): inputs that feed rank() and zone_table().

Covers: price-history order (same-day alert_previous before alert), listings.alert_flags in eval.flags,
merged_into (hidden, merged_links, chains), merged listings kept out of the medians / counts, and unknown
property type never flagged as a duplicate (FR-018, research R15, Article I).

Expected values are hand calculations from the specs, not output of the code under test.
"""
import json

import pytest

from app import scoring

ZONE = "zona-a"
DROP_FLAG = "bajada de precio acumulada"


def _zone(conn, zone=ZONE):
    conn.execute("INSERT OR IGNORE INTO zones(zone_id,name,municipality,level) VALUES(?,?,?,?)",
                 (zone, zone, "test", "municipality"))


def _put(conn, lid, price=400_000.0, area=100.0, beds=3, ptype="piso", zone=ZONE, merged_into=None,
         alert_flags=None):
    _zone(conn, zone)
    conn.execute(
        "INSERT INTO listings(id,source,url,property_type,price,area_m2,bedrooms,zone_id,development,"
        "merged_into,alert_flags) VALUES(?,?,?,?,?,?,?,?,0,?,?)",
        (lid, "alert", f"https://x.test/{lid}", ptype, price, area, beds, zone, merged_into, alert_flags))
    conn.commit()
    return lid


def _hist(conn, lid, day, price, origin):
    conn.execute("INSERT INTO price_history(listing_id,day,price,origin) VALUES(?,?,?,?)",
                 (lid, day, price, origin))
    conn.commit()


def _rank(conn, needs):
    return {r["id"]: r for r in scoring.rank(conn, needs)}


# --- 1. price-history order -------------------------------------------------------------------------

def test_same_day_alert_previous_is_read_before_alert_even_with_higher_rowid(conn, needs):
    _put(conn, "L", price=645_000.0)
    # The 'alert' row is inserted FIRST (lower rowid); both rows share the day.
    _hist(conn, "L", "2026-05-01", 645_000.0, "alert")
    _hist(conn, "L", "2026-05-01", 670_000.0, "alert_previous")
    ev = _rank(conn, needs)["L"]["eval"]
    # Required order: 670000 (previous) then 645000 (current).
    # drop = 1 - 645000/670000 = 25000/670000 = 0.0373134...  -> formatted with .1% = "3.7%"
    # momentum = clamp(drop / 0.10) = 0.373134...
    assert "bajada de precio acumulada 3.7%" in ev["flags"]
    assert ev["price_drop"] == pytest.approx(25_000 / 670_000, abs=1e-6)
    assert ev["components"]["momentum"] == pytest.approx(0.373134, abs=1e-5)
    # Wrong order (rowid): 645000 then 670000 -> drop = 1 - 670000/645000 = -0.0388 -> no flag, momentum 0.
    assert ev["price_drop"] > 0


def test_same_day_order_does_not_depend_on_insertion_order(conn, needs):
    _put(conn, "L", price=645_000.0)
    _hist(conn, "L", "2026-05-01", 670_000.0, "alert_previous")
    _hist(conn, "L", "2026-05-01", 645_000.0, "alert")
    ev = _rank(conn, needs)["L"]["eval"]
    assert "bajada de precio acumulada 3.7%" in ev["flags"]  # same hand value as above (25000/670000)


def test_earlier_day_always_precedes_later_day(conn, needs):
    _put(conn, "L", price=600_000.0)
    # day order wins over origin and rowid: 2026-05-01 (700000) first, 2026-05-02 (630000) last.
    # drop = 1 - 630000/700000 = 70000/700000 = 0.10 -> "10.0%", momentum = clamp(0.10/0.10) = 1.0
    _hist(conn, "L", "2026-05-02", 630_000.0, "alert")
    _hist(conn, "L", "2026-05-01", 700_000.0, "alert")
    ev = _rank(conn, needs)["L"]["eval"]
    assert "bajada de precio acumulada 10.0%" in ev["flags"]
    assert ev["components"]["momentum"] == pytest.approx(1.0)


# --- 2. alert_flags in ranking ----------------------------------------------------------------------

def test_alert_flags_appended_after_existing_flags_in_order_without_duplicates(conn, needs):
    _put(conn, "L")
    base = _rank(conn, needs)["L"]["eval"]["flags"]
    assert base  # the scorer always has some flags for a bare listing (e.g. no reference price)
    stored = ["bajó de precio en la alerta", "nuevo en tu búsqueda", "bajó de precio en la alerta", base[0]]
    conn.execute("UPDATE listings SET alert_flags=? WHERE id='L'", (json.dumps(stored, ensure_ascii=False),))
    conn.commit()
    flags = _rank(conn, needs)["L"]["eval"]["flags"]
    # Existing flags untouched and first; stored ones follow in stored order; the repeated stored text and
    # the stored text equal to an existing flag (base[0]) are not repeated.
    assert flags == base + ["bajó de precio en la alerta", "nuevo en tu búsqueda"]


@pytest.mark.parametrize("raw", [None, "", "not json {", '{"a": 1}', '"texto"', "5", "null"])
def test_unreadable_alert_flags_add_nothing_and_do_not_crash(conn, needs, raw):
    _put(conn, "L")
    base = _rank(conn, needs)["L"]["eval"]["flags"]
    conn.execute("UPDATE listings SET alert_flags=? WHERE id='L'", (raw,))
    conn.commit()
    assert _rank(conn, needs)["L"]["eval"]["flags"] == base


# --- 3. merged_into: hidden, merged_links, chains ---------------------------------------------------

def test_merged_listing_not_returned_and_target_carries_its_url(conn, needs):
    _put(conn, "T", beds=2)
    _put(conn, "M", beds=4, merged_into="T")
    rows = _rank(conn, needs)
    assert set(rows) == {"T"}
    assert rows["T"]["merged_links"] == ["https://x.test/M"]


def test_merged_links_empty_list_when_nothing_merged(conn, needs):
    _put(conn, "T")
    assert _rank(conn, needs)["T"]["merged_links"] == []


def test_merge_chain_resolves_to_final_target(conn, needs):
    # A merged into B, B merged into C: only C is visible and it carries the urls of BOTH A and B.
    _put(conn, "C", beds=1)
    _put(conn, "B", beds=2, merged_into="C")
    _put(conn, "A", beds=3, merged_into="B")
    rows = _rank(conn, needs)
    assert set(rows) == {"C"}
    assert sorted(rows["C"]["merged_links"]) == ["https://x.test/A", "https://x.test/B"]


# --- 4. merged listings do not feed medians / counts -------------------------------------------------

def _market(needs, min_n):
    needs["market"]["min_listings_for_median"] = min_n
    needs["market"]["asking_markup"] = 0.0
    return needs


def test_merged_listing_does_not_change_the_own_listings_median(conn, needs):
    needs = _market(needs, 3)
    # Visible flats, 100 m2 each: 4000, 5000, 6000 EUR/m2. Merged duplicate of T: 10000 EUR/m2.
    _put(conn, "T", price=400_000.0, beds=1)
    _put(conn, "V2", price=500_000.0, beds=2)
    _put(conn, "V3", price=600_000.0, beds=3)
    _put(conn, "M", price=1_000_000.0, beds=4, merged_into="T")
    ev = _rank(conn, needs)["T"]["eval"]
    # Visible only: median(4000, 5000, 6000) = 5000. (With the merged one: median of 4 = 5500.)
    # discount = 1 - 4000/5000 = 0.2 ; price component = clamp(0.5 + 0.2*2.5) = 1.0
    assert ev["benchmark_source"] == "mediana de tus anuncios"
    assert ev["benchmark_m2"] == pytest.approx(5000.0)
    assert ev["discount_vs_benchmark"] == pytest.approx(0.2)


def test_merged_listing_does_not_count_towards_minimum_listings(conn, needs):
    needs = _market(needs, 3)
    # 2 visible + 1 merged = 3 rows, but only 2 count: below the minimum of 3 -> no benchmark at all.
    _put(conn, "T", price=400_000.0, beds=1)
    _put(conn, "V2", price=500_000.0, beds=2)
    _put(conn, "M", price=450_000.0, beds=4, merged_into="T")
    ev = _rank(conn, needs)["T"]["eval"]
    assert ev["benchmark_m2"] is None
    assert ev["components"]["price"] is None
    assert "sin referencia de precio para esta zona" in ev["flags"]


def test_zone_table_ignores_merged_listings(conn, needs):
    needs = _market(needs, 2)
    _put(conn, "T", price=400_000.0, beds=1)      # 4000 EUR/m2
    _put(conn, "V2", price=500_000.0, beds=2)     # 5000 EUR/m2
    _put(conn, "M", price=1_000_000.0, beds=4, merged_into="T")  # 10000 EUR/m2, merged
    row = next(r for r in scoring.zone_table(conn, needs) if r["zone_id"] == ZONE)
    # Visible: n = 2, median(4000, 5000) = 4500. (With the merged one: n = 3, median = 5000.)
    assert row["listings"]["flat"]["n"] == 2
    assert row["listings"]["flat"]["median_m2"] == pytest.approx(4500.0)


# --- 5. unknown property type is never a duplicate (R15 / Article I) --------------------------------

@pytest.mark.parametrize("ptype", [None, "", "otro"])
def test_unknown_property_type_not_flagged_as_duplicate(conn, needs, ptype):
    # Identical zone, bedrooms, area (0 % diff <= 3 %) and price (0 % diff <= 5 %); only the type is
    # unknown/unrecognised on both, so "same type" cannot be established -> no flag on either.
    _put(conn, "A", ptype=ptype)
    _put(conn, "B", ptype=ptype)
    rows = _rank(conn, needs)
    for lid in ("A", "B"):
        assert [f for f in rows[lid]["eval"]["flags"] if "duplicado" in f] == []


def test_known_type_control_is_still_flagged(conn, needs):
    _put(conn, "A", ptype="piso")
    _put(conn, "B", ptype="piso")
    rows = _rank(conn, needs)
    assert [f for f in rows["A"]["eval"]["flags"] if "duplicado" in f] == ["posible duplicado de B"]
