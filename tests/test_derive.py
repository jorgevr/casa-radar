"""Listing derivation from sightings, core cases (data-model § Extended: listings, research R11)."""
from pathlib import Path

import pytest

from app import alerts, derive, zones


@pytest.fixture(autouse=True)
def no_aliases(tmp_path, monkeypatch):
    monkeypatch.setattr(zones, "ALIASES_PATH", tmp_path / "zone_aliases.yaml")


def _sighting(conn, email_id, code, seen_at, **fields):
    conn.execute("INSERT INTO alert_emails(email_id, origin, alert_date, alert_type, outcome) "
                 "VALUES(?, 'file', ?, 'new_listing', 'imported')", (email_id, seen_at))
    row = {"email_id": email_id, "listing_id": f"idealista:{code}", "alert_type": "new_listing",
           "seen_at": seen_at, "development": 0, "link_tracking": f"https://www.idealista.com/inmueble/{code}/?x=1",
           "link_direct": f"https://www.idealista.com/inmueble/{code}/", **fields}
    conn.execute(f"INSERT INTO sightings({','.join(row)}) VALUES({','.join('?' * len(row))})", list(row.values()))
    return row["listing_id"]


def test_one_new_listing_sighting_creates_the_listing(conn):
    lid = _sighting(conn, "<a@x>", "112923327", "2026-10-27T19:48:40+01:00", price=560_000, area_m2=175,
                    bedrooms=4, type_text="Chalet pareado", property_type="pareado", location_text="Sector 3, Getafe")
    derive.derive_listing(conn, lid)
    row = conn.execute("SELECT * FROM listings WHERE id=?", (lid,)).fetchone()
    assert (row["source"], row["url"], row["title"]) == (
        "idealista", "https://www.idealista.com/inmueble/112923327/", "Chalet pareado en Sector 3, Getafe")
    assert (row["price"], row["area_m2"], row["bedrooms"], row["property_type"]) == (560_000, 175, 4, "pareado")
    assert (row["zone_id"], row["municipality"], row["location_text"]) == ("getafe", "Getafe", "Sector 3, Getafe")
    assert (row["first_seen"], row["last_seen"], row["published_at"]) == ("2026-10-27",) * 3
    assert row["price_updated_at"] is None
    history = conn.execute("SELECT day, price, origin, email_id FROM price_history WHERE listing_id=?", (lid,)).fetchall()
    assert [tuple(h) for h in history] == [("2026-10-27", 560_000, "alert", "<a@x>")]


def test_absent_attribute_stays_null(conn):
    lid = _sighting(conn, "<b@x>", "1", "2026-10-27T10:00:00+01:00", price=300_000, location_text="Getafe")
    derive.derive_listing(conn, lid)
    row = conn.execute("SELECT * FROM listings WHERE id=?", (lid,)).fetchone()
    for col in ("area_m2", "bedrooms", "floor", "exterior", "elevator", "garage", "property_type", "new_build"):
        assert row[col] is None, col


def test_rederiving_does_not_duplicate_history(conn):
    lid = _sighting(conn, "<c@x>", "2", "2026-10-27T10:00:00+01:00", price=300_000)
    derive.derive_listing(conn, lid)
    derive.derive_listing(conn, lid)
    assert conn.execute("SELECT COUNT(*) FROM listings").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM price_history WHERE listing_id=?", (lid,)).fetchone()[0] == 1


def test_unrecognised_zone_stays_null(conn):
    lid = _sighting(conn, "<d@x>", "3", "2026-10-27T10:00:00+01:00", price=300_000,
                    location_text="alto de San Isidro, San Isidro, Madrid")
    derive.derive_listing(conn, lid)
    row = conn.execute("SELECT zone_id, location_text FROM listings WHERE id=?", (lid,)).fetchone()
    assert tuple(row) == (None, "alto de San Isidro, San Isidro, Madrid")


# ── Phase 2 checkpoint: process_message on a fixture creates the expected listing ──
EMAILS = Path(__file__).parent / "fixtures" / "emails"


def _process(conn, code):
    run_id = alerts.start_run(conn, "file_cli")
    raw = next(EMAILS.glob(f"*_{code}.eml")).read_bytes()
    return run_id, alerts.process_message(conn, raw, origin="file", file_name=f"{code}.eml", run_id=run_id)


def test_process_new_listing_fixture(conn, no_network):
    run_id, out = _process(conn, "112921923")
    assert (out.outcome, out.listing_id) == ("imported", "idealista:112921923")
    row = conn.execute("SELECT * FROM listings WHERE id='idealista:112921923'").fetchone()
    assert (row["price"], row["area_m2"], row["bedrooms"], row["floor"]) == (509_990, 150, 4, 2)
    assert (row["exterior"], row["elevator"], row["garage"], row["zone_id"]) == (1, 1, 1, "alcala-de-henares")
    assert (row["published_at"], row["first_seen"], row["development"]) == ("2026-10-27", "2026-10-27", 0)
    email_row = conn.execute("SELECT * FROM alert_emails").fetchone()
    assert (email_row["outcome"], email_row["alert_type"], email_row["reader_version"]) == (
        "imported", "new_listing", "idealista-2026.10")
    assert email_row["raw"] == next(EMAILS.glob("*_112921923.eml")).read_bytes()
    assert (email_row["first_run_id"], email_row["last_run_id"]) == (run_id, run_id)


def test_process_price_drop_fixture_for_unknown_listing(conn, no_network):
    _, out = _process(conn, "112842548")
    assert out.outcome == "imported"
    row = conn.execute("SELECT * FROM listings WHERE id='idealista:112842548'").fetchone()
    assert (row["price"], row["zone_id"], row["published_at"]) == (645_000, "torrejon-de-ardoz", None)
    history = conn.execute("SELECT day, price, origin FROM price_history WHERE listing_id='idealista:112842548' "
                           "ORDER BY day, origin='alert_previous' DESC, rowid").fetchall()
    assert [tuple(h) for h in history] == [("2026-10-26", 670_000, "alert_previous"), ("2026-10-26", 645_000, "alert")]


def test_process_development_fixture(conn, no_network):
    _, out = _process(conn, "112882173")
    row = conn.execute("SELECT * FROM listings WHERE id=?", (out.listing_id,)).fetchone()
    assert (row["development"], row["new_build"], row["property_type"], row["zone_id"]) == (1, 1, None, "brunete")
    assert row["url"] == "https://www.idealista.com/obra-nueva/112882173/"
    assert row["unit_description"].startswith("BRUNETE FUTURO")


def test_same_email_twice_is_already_processed(conn, no_network):
    run_id, _ = _process(conn, "112923327")
    raw = next(EMAILS.glob("*_112923327.eml")).read_bytes()
    out = alerts.process_message(conn, raw, origin="file", run_id=run_id)
    assert out.outcome == "already"
    assert conn.execute("SELECT COUNT(*) FROM alert_emails").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM sightings").fetchone()[0] == 1


def test_run_counters(conn, no_network):
    run_id = alerts.start_run(conn, "file_cli")
    for path in sorted(EMAILS.glob("*.eml")):
        alerts.process_message(conn, path.read_bytes(), origin="file", file_name=path.name, run_id=run_id)
    alerts.finish_run(conn, run_id, "ok")
    run = conn.execute("SELECT * FROM import_runs WHERE run_id=?", (run_id,)).fetchone()
    assert (run["status"], run["n_found"], run["n_imported"], run["n_already"], run["n_rejected"], run["n_failed"]) == (
        "ok", 12, 11, 0, 1, 0)
    assert run["n_new_listings"] == 11 and run["finished_at"] is not None
    assert conn.execute("SELECT COUNT(*) FROM listings").fetchone()[0] == 11
