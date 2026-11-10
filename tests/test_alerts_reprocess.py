"""Re-process stored alert emails (T044, US4-3, FR-009, FR-010, research R11, data-model "alert_emails").

`alerts.reprocess(conn, scope="failed" | "all")` re-reads the stored raw bytes with the current reader,
replaces the email's sightings and re-derives the touched listings. "failed" means stored emails that did
not produce a listing (outcome failed or rejected: data-model "state transitions") and whose reader_version
is older than the current one; "all" means every stored email.

Expected values are written by hand from the fixtures, never from running the code:
  * DROP_NAME (112842548) is a price drop 670.000 -> 645.000 on 2026-10-26.
  * the follow-up built in reprocess_support is a second drop 645.000 -> 630.000 on 2026-10-28, so the
    listing's current price is the latest sighting's, 630.000 (R11), first/last seen 2026-10-26/2026-10-28,
    price_updated_at 2026-10-28 (the latest sighting whose price differs from the one before).
  * 3 stored emails = one imported, the 2021 one rejected, one truncated failed -> 3 / 1 / 0 / 1 / 1.
Stored emails come from the anonymised fixtures, mutated in memory only. Tests use no network.
"""
import json

import pytest

from app import alerts, db, zones
from app.etl import indicators as ind_etl
from app.providers import idealista_alert as reader
from app.providers.idealista_alert import Problem

from .reprocess_support import (DROP_LISTING, DROP_NAME, NEW_NAME, NEW_VERSION, OLD_2021_NAME, OTHER_DROP_NAME,
                                fixture, followup_drop, message_id, newer_reader, snapshot, store, table,
                                truncated, with_text_part, without_run_columns)

OLD_VERSION = "idealista-2026.10"
COUNT_KEYS = ("n_found", "n_imported", "n_already", "n_rejected", "n_failed")


@pytest.fixture(autouse=True)
def no_aliases(tmp_path, monkeypatch):
    monkeypatch.setattr(zones, "ALIASES_PATH", tmp_path / "zone_aliases.yaml")


def _counts(summary):
    return tuple(summary[k] for k in COUNT_KEYS)


def _email(conn, email_id):
    return dict(conn.execute("SELECT * FROM alert_emails WHERE email_id=?", (email_id,)).fetchone())


def _listing(conn, listing_id):
    row = conn.execute("SELECT * FROM listings WHERE id=?", (listing_id,)).fetchone()
    return None if row is None else dict(row)


def _seed_failed(conn):
    """One truncated drop email, stored as failed by the current (old) reader. Returns (id, full raw, raw)."""
    full = fixture(DROP_NAME)
    broken = truncated(full, "broken-1")
    (out,) = store(conn, [broken])
    assert out.outcome == "failed" and "0 tarjetas" in out.reason  # precondition
    assert _listing(conn, DROP_LISTING) is None
    return out.email_id, full, broken


# -- US4-3: a newer reader that understands the case turns a failed email into an imported one ---------
def test_failed_email_is_imported_by_a_newer_reader(conn, monkeypatch, no_network):
    email_id, full, broken = _seed_failed(conn)
    before = _email(conn, email_id)
    newer_reader(monkeypatch, understands={email_id: full})

    summary = alerts.reprocess(conn, scope="failed")

    assert _counts(summary) == (1, 1, 0, 0, 0)
    after = _email(conn, email_id)
    assert after["outcome"] == "imported" and after["reason"] is None
    assert after["reader_version"] == NEW_VERSION
    assert after["raw"] == broken == before["raw"]  # the original raw is untouched (FR-010)
    assert after["content_hash"] == before["content_hash"]
    assert after["subject"] == before["subject"] and after["alert_date"] == before["alert_date"]
    assert conn.execute("SELECT COUNT(*) FROM alert_emails").fetchone()[0] == 1  # never deleted, never duplicated
    sightings = table(conn, "SELECT email_id, listing_id, price, previous_price FROM sightings")
    assert sightings == [{"email_id": email_id, "listing_id": DROP_LISTING, "price": 645000, "previous_price": 670000}]
    listing = _listing(conn, DROP_LISTING)  # re-derived: the fixture says 645.000
    assert listing["price"] == 645000
    assert listing["first_seen"] == listing["last_seen"] == "2026-10-26"


def test_failed_scope_ignores_emails_already_read_by_the_current_reader(conn, no_network):
    email_id, _, _ = _seed_failed(conn)  # stored with the current version

    summary = alerts.reprocess(conn, scope="failed")

    assert _counts(summary) == (0, 0, 0, 0, 0)  # nothing is older than the current reader
    assert _email(conn, email_id)["reader_version"] == OLD_VERSION == reader.READER_VERSION
    assert _listing(conn, DROP_LISTING) is None


def test_failed_scope_leaves_imported_and_current_version_emails_untouched(conn, monkeypatch, no_network):
    email_id, full, _ = _seed_failed(conn)
    (good,) = store(conn, [fixture(NEW_NAME)])
    assert good.outcome == "imported"
    good_before = snapshot(conn)
    newer_reader(monkeypatch, understands={email_id: full})
    # a failed email stored AFTER the upgrade carries the new version: "failed" must not re-read it
    (late,) = store(conn, [with_text_part(fixture(OTHER_DROP_NAME), "late-1")])
    assert late.outcome == "failed"
    late_before = _email(conn, late.email_id)

    summary = alerts.reprocess(conn, scope="failed")

    assert _counts(summary) == (1, 1, 0, 0, 0)  # only the old-version failed one
    after = snapshot(conn)
    # the imported email (old version, outcome imported) keeps its row, its sighting and its listing
    kept = [r for r in good_before["emails"] if r["email_id"] == good.email_id]
    assert [r for r in after["emails"] if r["email_id"] == good.email_id] == kept
    assert kept[0]["reader_version"] == OLD_VERSION
    assert [r for r in after["sightings"] if r["email_id"] == good.email_id] == [
        r for r in good_before["sightings"] if r["email_id"] == good.email_id]
    assert [r for r in after["listings"] if r["id"] == good.listing_id] == [
        r for r in good_before["listings"] if r["id"] == good.listing_id]
    # the late failed one is exactly as it was stored
    assert _email(conn, late.email_id) == late_before
    assert late_before["reader_version"] == NEW_VERSION and late_before["outcome"] == "failed"


def test_failed_scope_rereads_rejected_emails_with_an_older_version(conn, monkeypatch, no_network):
    (rej,) = store(conn, [fixture(OLD_2021_NAME)])
    assert rej.outcome == "rejected"
    raw = _email(conn, rej.email_id)["raw"]
    newer_reader(monkeypatch)  # new version number, same understanding

    summary = alerts.reprocess(conn, scope="failed")

    assert _counts(summary) == (1, 0, 0, 1, 0)
    row = _email(conn, rej.email_id)
    assert row["outcome"] == "rejected" and row["reason"] == alerts.REASON_UNSUPPORTED
    assert row["reader_version"] == NEW_VERSION and row["raw"] == raw
    assert conn.execute("SELECT COUNT(*) FROM listings").fetchone()[0] == 0  # FR-009


# -- scope "all" --------------------------------------------------------------------------------------
def test_all_scope_rereads_every_email_and_counts_sum(conn, monkeypatch, no_network):
    stored = store(conn, [fixture(NEW_NAME), fixture(OLD_2021_NAME), truncated(fixture(DROP_NAME), "broken-1")])
    assert [o.outcome for o in stored] == ["imported", "rejected", "failed"]
    before = snapshot(conn)
    newer_reader(monkeypatch)  # new version; the reader still cannot read the truncated one

    summary = alerts.reprocess(conn, scope="all")

    assert _counts(summary) == (3, 1, 0, 1, 1)
    assert summary["n_imported"] + summary["n_already"] + summary["n_rejected"] + summary["n_failed"] == summary["n_found"]
    after = snapshot(conn)
    assert len(after["emails"]) == 3
    for old, new in zip(before["emails"], after["emails"]):
        assert new["email_id"] == old["email_id"]
        assert new["raw"] == old["raw"] and new["content_hash"] == old["content_hash"]  # FR-010
        assert (new["outcome"], new["reason"]) == (old["outcome"], old["reason"])  # same understanding
        assert new["reader_version"] == NEW_VERSION
    # the imported email's sighting and listing are rebuilt to the same values
    assert after["sightings"] == before["sightings"]
    assert after["listings"] == before["listings"]
    assert after["history"] == before["history"]
    assert _listing(conn, DROP_LISTING) is None  # the failed one still creates nothing


def test_all_scope_replaces_sightings_and_rederives_listing(conn, monkeypatch, no_network):
    (out,) = store(conn, [fixture(NEW_NAME)])
    assert _listing(conn, out.listing_id)["bedrooms"] != 9  # precondition
    original = reader.read
    monkeypatch.setattr(reader, "READER_VERSION", NEW_VERSION)

    def read(msg):  # a newer reader that reads one value differently
        result = original(msg)
        for block in result.listings:
            block.bedrooms = 9
        return result

    monkeypatch.setattr(reader, "read", read)

    summary = alerts.reprocess(conn, scope="all")

    assert _counts(summary) == (1, 1, 0, 0, 0)
    assert table(conn, "SELECT email_id, bedrooms FROM sightings") == [{"email_id": out.email_id, "bedrooms": 9}]
    assert _listing(conn, out.listing_id)["bedrooms"] == 9  # re-derived from the new sighting
    assert conn.execute("SELECT COUNT(*) FROM listings").fetchone()[0] == 1


# -- still failing ------------------------------------------------------------------------------------
def test_email_that_still_fails_stays_failed_with_new_version_and_reason(conn, monkeypatch, no_network):
    email_id, _, broken = _seed_failed(conn)
    old_reason = _email(conn, email_id)["reason"]
    newer_reader(monkeypatch, problem=Problem("tarjeta del anuncio", "una tarjeta", "2 tarjetas"))

    summary = alerts.reprocess(conn, scope="failed")

    assert _counts(summary) == (1, 0, 0, 0, 1)
    row = _email(conn, email_id)
    assert row["outcome"] == "failed"
    assert row["reader_version"] == NEW_VERSION  # the attempt is recorded
    assert "2 tarjetas" in row["reason"] and row["reason"] != old_reason  # the reason is the new one
    assert row["raw"] == broken
    assert conn.execute("SELECT COUNT(*) FROM sightings").fetchone()[0] == 0  # FR-009
    assert conn.execute("SELECT COUNT(*) FROM listings").fetchone()[0] == 0
    assert [(p["email_id"], p["outcome"]) for p in summary["problems"]] == [(email_id, "failed")]
    assert "2 tarjetas" in summary["problems"][0]["reason"]


def test_failing_reprocess_keeps_the_sightings_and_the_listing_an_earlier_import_made(conn, monkeypatch, no_network):
    (out,) = store(conn, [fixture(DROP_NAME)])
    before = _listing(conn, DROP_LISTING)
    assert before["price"] == 645000
    sightings_before = table(conn, "SELECT * FROM sightings WHERE email_id=?", out.email_id)
    assert len(sightings_before) == 1
    newer_reader(monkeypatch, problem=Problem("tarjeta del anuncio", "una tarjeta", "0 tarjetas"))

    summary = alerts.reprocess(conn, scope="all")

    assert _counts(summary) == (1, 0, 0, 0, 1)
    assert _email(conn, out.email_id)["outcome"] == "failed"
    # user decision on review finding F3 (T044): "keep old sightings" when the new read is not imported (FU6a)
    assert table(conn, "SELECT * FROM sightings WHERE email_id=?", out.email_id) == sightings_before
    # FR-009 / FR-011: nothing is deleted or blanked; the
    # listing keeps what it had (an alert never writes null over a known value)
    assert _listing(conn, DROP_LISTING) == before


# -- R11: order of processing never changes derived values --------------------------------------------
def test_reprocess_gives_the_same_listings_as_a_fresh_import(conn, monkeypatch, tmp_path, no_network):
    first, follow = fixture(DROP_NAME), followup_drop(fixture(DROP_NAME), "followup-1")
    fresh = db.connect(":memory:")  # oldest email first, as a folder import orders them
    ind_etl.seed_madrid_districts(fresh)
    folder = tmp_path / "fresh"
    folder.mkdir()
    (folder / "a.eml").write_bytes(first)
    (folder / "b.eml").write_bytes(follow)
    alerts.import_paths(fresh, [folder])
    store(conn, [follow])  # other database: newest email stored first, then the oldest, then re-processed
    store(conn, [first])
    newer_reader(monkeypatch)

    summary = alerts.reprocess(conn, scope="all")

    assert _counts(summary) == (2, 2, 0, 0, 0)
    fresh_snap, again = without_run_columns(snapshot(fresh)), without_run_columns(snapshot(conn))
    for key in ("listings", "sightings", "history"):
        assert again[key] == fresh_snap[key], key
    # hand-calculated golden (module docstring), not copied from the code
    listing = _listing(conn, DROP_LISTING)
    assert listing["price"] == 630000
    assert (listing["first_seen"], listing["last_seen"]) == ("2026-10-26", "2026-10-28")
    assert listing["price_updated_at"] == "2026-10-28"
    assert listing["published_at"] is None  # no new_listing sighting
    assert conn.execute("SELECT COUNT(*) FROM sightings").fetchone()[0] == 2


# -- user-owned values survive (FR-023) ---------------------------------------------------------------
@pytest.mark.parametrize("origin", ["manual", "csv"])
def test_user_owned_price_survives_reprocess(conn, monkeypatch, no_network, origin):
    store(conn, [fixture(DROP_NAME)])
    conn.execute("UPDATE listings SET price=?, field_sources=? WHERE id=?",
                 (700000, json.dumps({"price": origin}), DROP_LISTING))
    conn.commit()
    newer_reader(monkeypatch)

    alerts.reprocess(conn, scope="all")

    listing = _listing(conn, DROP_LISTING)
    assert listing["price"] == 700000  # the alert says 645.000; the user's value stays
    assert json.loads(listing["field_sources"])["price"] == origin


def test_user_new_build_value_survives_reprocess(conn, monkeypatch, no_network):
    store(conn, [fixture(DROP_NAME)])
    conn.execute("UPDATE listings SET new_build=1, new_build_origin='user' WHERE id=?", (DROP_LISTING,))
    conn.commit()
    newer_reader(monkeypatch)

    alerts.reprocess(conn, scope="all")

    listing = _listing(conn, DROP_LISTING)
    assert (listing["new_build"], listing["new_build_origin"]) == (1, "user")


# -- idempotence --------------------------------------------------------------------------------------
@pytest.mark.parametrize("scope, first_counts, second_counts", [
    # "failed" re-reads the broken one (now understood) and the 2021 one (rejected, old version): 2 found,
    # 1 imported, 1 rejected; both then carry the new version, so the second run finds nothing
    ("failed", (2, 1, 0, 1, 0), (0, 0, 0, 0, 0)),
    # "all": broken (now imported), the new-listing fixture, and the 2021 one: 3 found, 2 imported, 1 rejected, twice
    ("all", (3, 2, 0, 1, 0), (3, 2, 0, 1, 0)),
])
def test_reprocess_twice_changes_nothing(conn, monkeypatch, no_network, scope, first_counts, second_counts):
    email_id, full, _ = _seed_failed(conn)
    store(conn, [fixture(NEW_NAME), fixture(OLD_2021_NAME)])
    newer_reader(monkeypatch, understands={email_id: full})

    first = alerts.reprocess(conn, scope=scope)
    after_first = snapshot(conn)
    second = alerts.reprocess(conn, scope=scope)

    assert _counts(first) == first_counts
    assert _counts(second) == second_counts
    assert snapshot(conn) == after_first


# -- the run row --------------------------------------------------------------------------------------
def test_reprocess_records_a_run(conn, monkeypatch, no_network):
    email_id, full, _ = _seed_failed(conn)
    import_run = _email(conn, email_id)["first_run_id"]
    newer_reader(monkeypatch, understands={email_id: full})

    summary = alerts.reprocess(conn, scope="failed")

    assert isinstance(summary["run_id"], int) and summary["run_id"] != import_run
    assert summary["kind"] == "reprocess" and summary["status"] == "ok"
    assert isinstance(summary["problems"], list) and isinstance(summary["notices"], list)
    runs = table(conn, "SELECT * FROM import_runs WHERE kind='reprocess'")
    assert len(runs) == 1
    run = runs[0]
    assert run["run_id"] == summary["run_id"] and run["status"] == "ok"
    assert run["started_at"] and run["finished_at"] and run["error"] is None
    assert (run["n_found"], run["n_imported"], run["n_failed"]) == (1, 1, 0)
    assert run["n_new_listings"] == 1  # the listing did not exist before
    row = _email(conn, email_id)
    assert row["first_run_id"] == import_run  # where it came from does not change
    assert row["last_run_id"] == summary["run_id"]


def test_reprocess_with_nothing_to_do_still_records_a_finished_run(conn, no_network):
    summary = alerts.reprocess(conn, scope="failed")

    assert _counts(summary) == (0, 0, 0, 0, 0)
    assert summary["kind"] == "reprocess" and summary["status"] == "ok"
    assert table(conn, "SELECT status, finished_at IS NOT NULL AS done FROM import_runs") == [
        {"status": "ok", "done": 1}]


def test_unknown_scope_is_refused_without_a_run(conn, no_network):
    with pytest.raises(ValueError):
        alerts.reprocess(conn, scope="everything")

    assert conn.execute("SELECT COUNT(*) FROM import_runs").fetchone()[0] == 0


def test_reprocess_reads_only_stored_emails_and_never_the_network(conn, monkeypatch, no_network):
    # no_network raises on any socket connect: the stored bytes are all the function needs (FR-010)
    email_id, full, _ = _seed_failed(conn)
    newer_reader(monkeypatch, understands={email_id: full})

    alerts.reprocess(conn, scope="all")

    assert message_id(_email(conn, email_id)["raw"]) == "<broken-1@example.invalid>"
