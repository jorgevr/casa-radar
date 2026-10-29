"""File import of alert emails (T016, US3): folders, .mbox, unsupported formats, timing.

Expected numbers come from the task text / Phase 3 Independent Test (12 fixtures: 11 alerts to import and
the 2021 "Nuevo piso" email, a layout without a sample, which must be rejected) and from the fixture
folder itself, not from running the code.
"""
import mailbox
import time

import pytest

from app import alerts, zones

from .conftest import EMAILS

# Fixtures that are importable alerts (everything except the 2021 one): a new-build development,
# a price drop and a resale chalet, picked by file name.
MBOX_FIXTURES = [
    "2026-10-22_nueva-obra-nueva_obra-nueva-en-tu-zona-personalizada_112882173.eml",
    "2026-10-23_bajada-de-precio_viviendas-en-tu-zona-personalizada_112658090.eml",
    "2026-10-27_nuevo-chalet-pareado_chalets-en-tu-zona-personalizada_112923327.eml",
]


@pytest.fixture(autouse=True)
def no_aliases(tmp_path, monkeypatch):
    monkeypatch.setattr(zones, "ALIASES_PATH", tmp_path / "zone_aliases.yaml")


def _counts(summary):
    return tuple(summary[k] for k in ("n_found", "n_imported", "n_already", "n_rejected", "n_failed"))


def test_import_fixture_folder(conn, no_network):
    assert len(list(EMAILS.glob("*.eml"))) == 12  # the fixture set the counts below refer to

    first = alerts.import_paths(conn, [EMAILS])

    # Phase 3 Independent Test: 12 emails: 11 imported, 0 already, 1 rejected, 0 failed (FR-002, SC-004)
    assert _counts(first) == (12, 11, 0, 1, 0)
    assert first["n_imported"] + first["n_already"] + first["n_rejected"] + first["n_failed"] == first["n_found"]
    # the single rejection is the 2021 email, reported with its subject/date as a problem line
    rejected = [p for p in first["problems"] if p["outcome"] == "rejected"]
    assert len(rejected) == 1
    assert rejected[0]["alert_date"].startswith("2021-03-10")
    assert not [p for p in first["problems"] if p["outcome"] == "failed"]

    # 11 listings, each with price, area (or development) and link (SC-002)
    listings = conn.execute("SELECT id, price, area_m2, development, url FROM listings").fetchall()
    assert len(listings) == 11
    assert first["n_new_listings"] == 11
    for row in listings:
        assert row["price"] is not None and row["price"] > 0, row["id"]
        assert row["area_m2"] is not None or row["development"] == 1, row["id"]
        assert row["url"] and row["url"].startswith("https://www.idealista.com/"), row["id"]
    assert conn.execute("SELECT COUNT(*) FROM alert_emails").fetchone()[0] == 12

    # second import: every email is already processed, nothing new
    second = alerts.import_paths(conn, [EMAILS])
    assert _counts(second) == (12, 0, 12, 0, 0)
    assert second["n_new_listings"] == 0
    assert conn.execute("SELECT COUNT(*) FROM listings").fetchone()[0] == 11
    assert conn.execute("SELECT COUNT(*) FROM alert_emails").fetchone()[0] == 12


def test_import_mbox_of_three_fixtures(conn, tmp_path, no_network):
    path = tmp_path / "alerts.mbox"
    box = mailbox.mbox(str(path))
    for name in MBOX_FIXTURES:
        box.add((EMAILS / name).read_bytes())
    box.flush()
    box.close()

    summary = alerts.import_paths(conn, [path])

    assert _counts(summary) == (3, 3, 0, 0, 0)
    assert conn.execute("SELECT COUNT(*) FROM listings").fetchone()[0] == 3
    # file name = "<mbox name>#<index>" (T018)
    names = sorted(r[0] for r in conn.execute("SELECT file_name FROM alert_emails"))
    assert len(names) == 3 and all(n.startswith("alerts.mbox#") for n in names)
    assert len(set(names)) == 3


def test_msg_file_is_reported_unsupported(conn, tmp_path, no_network):
    msg = tmp_path / "alerta.msg"
    msg.write_bytes(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1 not an rfc822 message")

    summary = alerts.import_paths(conn, [msg])

    reasons = [p["reason"] for p in summary["problems"]]
    assert any("unsupported file format: save as .eml" in r for r in reasons), summary
    assert summary["n_imported"] == 0
    assert conn.execute("SELECT COUNT(*) FROM listings").fetchone()[0] == 0


def _write_mbox_variant(tmp_path, variant):
    path = tmp_path / ("alerta.mbox" if variant == "eml-as-mbox" else "empty.mbox")
    if variant == "eml-as-mbox":
        # a real fixture saved under an .mbox name: it has no leading "From " line, so it is not an mbox
        path.write_bytes((EMAILS / MBOX_FIXTURES[0]).read_bytes())
    else:
        path.write_bytes(b"")
    return path


@pytest.mark.parametrize("variant", ["eml-as-mbox", "empty"])
def test_mbox_yielding_no_messages_is_reported(conn, tmp_path, no_network, variant):
    # Article VI, FR-002, SC-004: a supplied file that yields nothing must still appear in the summary
    path = _write_mbox_variant(tmp_path, variant)

    summary = alerts.import_paths(conn, [path])

    # one file = one found item = one failed item (by hand: 1 / 0 / 0 / 0 / 1)
    assert _counts(summary) == (1, 0, 0, 0, 1), summary
    assert summary["n_imported"] + summary["n_already"] + summary["n_rejected"] + summary["n_failed"] == summary["n_found"]
    assert len(summary["problems"]) == 1
    problem = summary["problems"][0]
    assert problem["outcome"] == "failed"
    assert problem["email_id"] == path.name
    assert isinstance(problem["reason"], str) and problem["reason"].strip()
    assert conn.execute("SELECT COUNT(*) FROM listings").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM alert_emails").fetchone()[0] == 0


def test_folder_expansion_is_not_recursive(conn, tmp_path, no_network):
    folder = tmp_path / "parent"
    sub = folder / "sub"
    sub.mkdir(parents=True)
    (sub / MBOX_FIXTURES[0]).write_bytes((EMAILS / MBOX_FIXTURES[0]).read_bytes())

    summary = alerts.import_paths(conn, [folder])

    # the only .eml is one level down, so the folder holds no .eml/.mbox of its own: nothing found
    assert _counts(summary) == (0, 0, 0, 0, 0), summary
    assert summary["problems"] == []
    assert conn.execute("SELECT COUNT(*) FROM alert_emails").fetchone()[0] == 0


@pytest.mark.slow
def test_fixture_import_under_five_seconds(conn, no_network):
    start = time.perf_counter()
    summary = alerts.import_paths(conn, [EMAILS])
    elapsed = time.perf_counter() - start

    assert summary["n_found"] == 12
    assert elapsed < 5, f"SC-001: fixture import took {elapsed:.2f}s"
