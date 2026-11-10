"""T032 golden test (money, Article VII): new-build status taken from the alert category (FR-033, US1-10).

Rules under test (data-model.md "Derivation (R11)" and "Flag texts"; spec FR-033, US1-10):
- new_build = 1 with new_build_origin 'email' when a sighting states it (new_build_stated);
- else new_build = 1 with new_build_origin 'category' when a sighting's category is 'new-build';
- a user value (new_build_origin 'user') is never changed;
- a category other than 'new-build' never sets new_build; absence is never "no" (Article I);
- the cost estimate of a listing whose new-build comes from the category shows the flag
  'obra nueva según la categoría de la alerta, confirma' (exact text, data-model Flag texts).

Where the numbers come from. The cost estimate is `rank(...)[i]["eval"]["mortgage"]` (scoring.evaluate ->
mortgage.simulate -> mortgage.purchase_costs, app/mortgage.py): taxes = price * (iva_new + ajd) for a new
build, price * itp otherwise. The rates are read by hand from config/needs.example.yaml, section `costs:`:
itp 0.06, ajd 0.0075, iva_new 0.10 (Comunidad de Madrid general rates). Hand calculation for a 400.000 EUR price:
  new build : IVA 10 %   = 400.000 * 0.10   = 40.000
              AJD 0.75 % = 400.000 * 0.0075 =  3.000   -> taxes 43.000
  second hand: ITP 6 %   = 400.000 * 0.06   = 24.000   -> taxes 24.000
None of these figures is taken from running the code.

Data: sightings are written with an explicit `category` column (the category rules, T033/T034, do not exist
yet; the tests set the value directly) and listings are built by derive.derive_listing. The user's choice
(PATCH /api/listings/{id} {"new_build": false}, T035) is applied as the route will store it, by
`UPDATE listings SET new_build=?, new_build_origin='user'`, followed by derive.derive_listing as the route
does for other user values; the PATCH route itself is covered by T035's tests.
"""
import copy

import pytest

from app import alerts, derive, scoring, zones

CATEGORY_FLAG = "obra nueva según la categoría de la alerta, confirma"
PRICE = 400_000.0
# Hand-calculated, see the module docstring.
TAXES_NEW_BUILD = 43_000.0   # 400.000 * (0.10 IVA + 0.0075 AJD)
TAXES_SECOND_HAND = 24_000.0  # 400.000 * 0.06 ITP
LID = "idealista:9001"


@pytest.fixture(autouse=True)
def no_aliases(tmp_path, monkeypatch):
    monkeypatch.setattr(zones, "ALIASES_PATH", tmp_path / "zone_aliases.yaml")


@pytest.fixture
def costed_needs(needs):
    """The example needs plus savings, so that rank() produces the cost estimate (eval.mortgage)."""
    n = copy.deepcopy(needs)
    n["finance"]["savings"] = 200_000.0
    # sanity: the rates the hand calculation relies on (config/needs.example.yaml `costs:`)
    assert (n["costs"]["itp"], n["costs"]["ajd"], n["costs"]["iva_new"]) == (0.06, 0.0075, 0.10)
    return n


def _sighting(conn, email_id, seen_at, category=None, new_build_stated=None, price=PRICE, code="9001",
              alert_type="new_listing"):
    conn.execute("INSERT INTO alert_emails(email_id, origin, alert_date, alert_type, outcome, category) "
                 "VALUES(?, 'file', ?, ?, 'imported', ?)", (email_id, seen_at, alert_type, category))
    row = {"email_id": email_id, "listing_id": f"idealista:{code}", "alert_type": alert_type, "seen_at": seen_at,
           "price": price, "development": 0, "location_text": "Getafe", "new_build_stated": new_build_stated,
           "category": category,
           "link_tracking": f"https://www.idealista.com/inmueble/{code}/?x=1",
           "link_direct": f"https://www.idealista.com/inmueble/{code}/"}
    conn.execute(f"INSERT INTO sightings({','.join(row)}) VALUES({','.join('?' * len(row))})", list(row.values()))
    derive.derive_listing(conn, row["listing_id"])
    conn.commit()
    return row["listing_id"]


def _row(conn, lid=LID):
    return conn.execute("SELECT * FROM listings WHERE id=?", (lid,)).fetchone()


def _user_sets(conn, value, lid=LID):
    """What PATCH {"new_build": value} stores (T035) and the re-derivation that follows."""
    conn.execute("UPDATE listings SET new_build=?, new_build_origin='user' WHERE id=?", (value, lid))
    derive.derive_listing(conn, lid)
    conn.commit()


def _eval(conn, needs, lid=LID):
    return next(r for r in scoring.rank(conn, needs) if r["id"] == lid)["eval"]


# --- (a) category new-build, email silent ------------------------------------------------------------

def test_new_build_from_category_golden(conn, costed_needs):
    _sighting(conn, "<a1@x>", "2026-10-27T10:00:00+01:00", category="new-build")
    row = _row(conn)
    assert row["url"].startswith("https://www.idealista.com/inmueble/")   # a /inmueble/ listing
    assert (row["new_build"], row["new_build_origin"]) == (1, "category")
    ev = _eval(conn, costed_needs)
    # app/mortgage.py purchase_costs: new build -> taxes = price * (iva_new + ajd); rates from
    # config/needs.example.yaml costs: iva_new 0.10, ajd 0.0075.
    # 400.000 * 0.10 = 40.000 (IVA) + 400.000 * 0.0075 = 3.000 (AJD) = 43.000
    assert ev["mortgage"]["taxes"] == pytest.approx(TAXES_NEW_BUILD)
    assert ev["flags"].count(CATEGORY_FLAG) == 1


# --- (b) the user then says second-hand --------------------------------------------------------------

def test_user_second_hand_replaces_category_value_and_costs(conn, costed_needs):
    _sighting(conn, "<b1@x>", "2026-10-27T10:00:00+01:00", category="new-build")
    assert _row(conn)["new_build_origin"] == "category"
    _user_sets(conn, 0)
    row = _row(conn)
    assert (row["new_build"], row["new_build_origin"]) == (0, "user")
    ev = _eval(conn, costed_needs)
    # second hand -> taxes = price * itp (app/mortgage.py purchase_costs; needs.example.yaml costs: itp 0.06)
    # 400.000 * 0.06 = 24.000
    assert ev["mortgage"]["taxes"] == pytest.approx(TAXES_SECOND_HAND)
    assert CATEGORY_FLAG not in ev["flags"]          # US1-10: the flag disappears once the user decides


# --- (c) stated new-build: origin email, never the category flag -------------------------------------

def test_stated_new_build_is_origin_email_without_category_flag(conn, costed_needs):
    # statement by the email (new_build_stated, as the reader sets it for "Nueva obra nueva" / /obra-nueva/)
    _sighting(conn, "<c1@x>", "2026-10-27T10:00:00+01:00", new_build_stated=1)
    row = _row(conn)
    assert (row["new_build"], row["new_build_origin"]) == (1, "email")
    ev = _eval(conn, costed_needs)
    assert ev["mortgage"]["taxes"] == pytest.approx(TAXES_NEW_BUILD)   # 400.000 * (0.10 + 0.0075) = 43.000
    assert CATEGORY_FLAG not in ev["flags"]


def test_stated_new_build_wins_over_category(conn, costed_needs):
    # both the email and the category say new-build: the email is the origin (data-model: email first)
    _sighting(conn, "<c2@x>", "2026-10-27T10:00:00+01:00", category="new-build", new_build_stated=1)
    row = _row(conn)
    assert (row["new_build"], row["new_build_origin"]) == (1, "email")
    ev = _eval(conn, costed_needs)
    assert ev["mortgage"]["taxes"] == pytest.approx(TAXES_NEW_BUILD)
    assert CATEGORY_FLAG not in ev["flags"]


def test_real_nueva_obra_nueva_fixture_is_origin_email(conn, costed_needs, fixture_emails):
    # real anonymised alert, subject "Nueva obra nueva", link /obra-nueva/ (tests/fixtures/emails)
    path = next(p for p in fixture_emails if p.name.endswith("_112882173.eml"))
    out = alerts.process_message(conn, path.read_bytes(), origin="file", file_name=path.name,
                                 run_id=alerts.start_run(conn, "file_cli"))
    assert out.outcome == "imported"
    assert "/obra-nueva/" in _row(conn, out.listing_id)["url"]
    # even if the alert's category is also new-build, a stated new build is origin 'email'
    conn.execute("UPDATE sightings SET category='new-build' WHERE listing_id=?", (out.listing_id,))
    derive.derive_listing(conn, out.listing_id)
    conn.commit()
    row = _row(conn, out.listing_id)
    assert (row["new_build"], row["new_build_origin"]) == (1, "email")
    assert CATEGORY_FLAG not in _eval(conn, costed_needs, out.listing_id)["flags"]


# --- (d) a user value is never overridden by the category -------------------------------------------

def test_category_never_overrides_user_second_hand(conn, costed_needs):
    _sighting(conn, "<d1@x>", "2026-10-26T10:00:00+01:00")           # no category yet
    assert _row(conn)["new_build"] is None
    _user_sets(conn, 0)
    _sighting(conn, "<d2@x>", "2026-10-27T10:00:00+01:00", category="new-build")   # later alert, new-build category
    row = _row(conn)
    assert (row["new_build"], row["new_build_origin"]) == (0, "user")
    ev = _eval(conn, costed_needs)
    assert ev["mortgage"]["taxes"] == pytest.approx(TAXES_SECOND_HAND)   # 400.000 * 0.06 = 24.000
    assert CATEGORY_FLAG not in ev["flags"]


# --- (e) a category other than new-build never sets new_build ---------------------------------------

@pytest.mark.parametrize("category", ["flat", "house", None])
def test_other_category_never_sets_new_build(conn, costed_needs, category):
    _sighting(conn, "<e1@x>", "2026-10-27T10:00:00+01:00", category=category)
    row = _row(conn)
    assert (row["new_build"], row["new_build_origin"]) == (None, None)    # absent is unknown, never "no"
    ev = _eval(conn, costed_needs)
    assert ev["mortgage"]["taxes"] == pytest.approx(TAXES_SECOND_HAND)   # unknown costs as second hand: 24.000
    assert CATEGORY_FLAG not in ev["flags"]
