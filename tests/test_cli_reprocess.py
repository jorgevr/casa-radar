"""`reprocess-emails [--failed | --all]` (T045, contracts/cli.md).

Contract: re-runs the current reader over stored emails, default `--failed`, without files or mailbox; same
summary format as the other commands; exit code 0, or 1 when an email failed (as `import-emails`).
Expected summary lines are written by hand: one fixture-derived email = "1 email: ..."; the plural rule of the
existing summary (0 and 2+ take the plural) gives "0 ya procesados". Emails are stored by the real
`import-emails` command from temporary copies of the anonymised fixtures (mutated in memory), so the
database the command opens is the one CASA_DB points at (conftest keeps it in tmp_path).
"""
import sqlite3

import pytest

from app import cli, db, zones

from .reprocess_support import (DROP_LISTING, DROP_NAME, NEW_NAME, OLD_2021_NAME, NEW_VERSION, fixture,
                                newer_reader, truncated)


@pytest.fixture(autouse=True)
def no_aliases(tmp_path, monkeypatch):
    monkeypatch.setattr(zones, "ALIASES_PATH", tmp_path / "zone_aliases.yaml")


def _seed(tmp_path, capsys, *raws):
    """Store emails through the real import command; its own output and exit code are not under test."""
    folder = tmp_path / "seed"
    folder.mkdir(exist_ok=True)
    for i, raw in enumerate(raws):
        (folder / f"s{i}.eml").write_bytes(raw)
    cli.main(["import-emails", str(folder)])
    capsys.readouterr()


def _run(capsys, *args):
    code = cli.main(["reprocess-emails", *args])
    return code, capsys.readouterr().out


def _rows(sql, *args):
    c = sqlite3.connect(db.DB_PATH)
    c.row_factory = sqlite3.Row
    try:
        return [dict(r) for r in c.execute(sql, args).fetchall()]
    finally:
        c.close()


def _broken_and_full():
    full = fixture(DROP_NAME)
    return truncated(full, "broken-1"), full


def test_default_is_failed_and_imports_what_the_newer_reader_understands(tmp_path, capsys, monkeypatch, no_network):
    broken, full = _broken_and_full()
    _seed(tmp_path, capsys, broken, fixture(NEW_NAME))
    newer_reader(monkeypatch, understands={"<broken-1@example.invalid>": full})

    code, out = _run(capsys)  # no flag: --failed

    assert code == 0
    # only the failed email is re-read: the imported one is left alone
    assert "1 email: 1 importado, 0 ya procesados, 0 rechazados, 0 fallidos" in out
    assert "FALLO" not in out
    rows = _rows("SELECT outcome, reader_version FROM alert_emails WHERE email_id='<broken-1@example.invalid>'")
    assert rows == [{"outcome": "imported", "reader_version": NEW_VERSION}]
    assert _rows("SELECT price FROM listings WHERE id=?", DROP_LISTING) == [{"price": 645000}]
    assert _rows("SELECT COUNT(*) AS n FROM import_runs WHERE kind='reprocess'") == [{"n": 1}]


def test_explicit_failed_flag_matches_the_default(tmp_path, capsys, monkeypatch, no_network):
    broken, full = _broken_and_full()
    _seed(tmp_path, capsys, broken)
    newer_reader(monkeypatch, understands={"<broken-1@example.invalid>": full})

    code, out = _run(capsys, "--failed")

    assert code == 0
    assert "1 email: 1 importado, 0 ya procesados, 0 rechazados, 0 fallidos" in out


def test_all_flag_rereads_every_stored_email(tmp_path, capsys, monkeypatch, no_network):
    broken, full = _broken_and_full()
    _seed(tmp_path, capsys, broken, fixture(NEW_NAME), fixture(OLD_2021_NAME))
    newer_reader(monkeypatch, understands={"<broken-1@example.invalid>": full})

    code, out = _run(capsys, "--all")

    assert code == 0
    # 3 stored: the broken one now imported, the new-listing fixture imported, the 2021 one rejected again
    assert "3 emails: 2 importados, 0 ya procesados, 1 rechazado, 0 fallidos" in out
    assert "RECHAZADO 2021-03-10" in out
    assert "tipo de alerta no soportado" in out
    versions = {r["reader_version"] for r in _rows("SELECT reader_version FROM alert_emails")}
    assert versions == {NEW_VERSION}


def test_failed_flag_leaves_imported_emails_with_their_old_version(tmp_path, capsys, monkeypatch, no_network):
    broken, full = _broken_and_full()
    _seed(tmp_path, capsys, broken, fixture(NEW_NAME))
    newer_reader(monkeypatch, understands={"<broken-1@example.invalid>": full})

    _run(capsys, "--failed")

    versions = {r["email_id"]: r["reader_version"] for r in _rows("SELECT email_id, reader_version FROM alert_emails")}
    assert versions.pop("<broken-1@example.invalid>") == NEW_VERSION
    assert list(versions.values()) == ["idealista-2026.10"]  # the imported one kept its version


def test_email_that_still_fails_is_listed_and_exit_code_is_1(tmp_path, capsys, monkeypatch, no_network):
    broken, _ = _broken_and_full()
    _seed(tmp_path, capsys, broken)
    newer_reader(monkeypatch)  # a newer version number that still cannot read the truncated card

    code, out = _run(capsys, "--failed")

    assert code == 1  # an email failed, as with import-emails
    assert "1 email: 0 importados, 0 ya procesados, 0 rechazados, 1 fallido" in out
    assert out.count("FALLO") == 1
    assert "2026-10-26" in out and "0 tarjetas" in out  # date and what was found (evidence)
    assert _rows("SELECT COUNT(*) AS n FROM listings") == [{"n": 0}]


def test_nothing_stored_prints_a_zero_summary_and_exits_0(capsys, no_network):
    code, out = _run(capsys)

    assert code == 0
    assert "0 emails: 0 importados, 0 ya procesados, 0 rechazados, 0 fallidos" in out


def test_failed_with_current_reader_version_finds_nothing(tmp_path, capsys, no_network):
    broken, _ = _broken_and_full()
    _seed(tmp_path, capsys, broken)  # stored by the current reader, still the current reader

    code, out = _run(capsys, "--failed")

    assert code == 0  # nothing re-read, nothing newly failed
    assert "0 emails: 0 importados, 0 ya procesados, 0 rechazados, 0 fallidos" in out


def test_failed_and_all_together_are_refused_by_the_parser(capsys):
    with pytest.raises(SystemExit) as exc:
        cli.main(["reprocess-emails", "--failed", "--all"])  # "[--failed | --all]": mutually exclusive

    assert exc.value.code == 2
    assert "not allowed with argument" in capsys.readouterr().err  # not merely "unknown command"


def test_command_needs_no_files_or_mailbox_and_prints_no_secret(tmp_path, capsys, monkeypatch, no_network):
    broken, full = _broken_and_full()
    _seed(tmp_path, capsys, broken)
    newer_reader(monkeypatch, understands={"<broken-1@example.invalid>": full})

    code, out = _run(capsys, "--all")  # no_network refuses any connection; CASA_APPDATA stays unused

    assert code == 0
    lowered = out.lower()
    for word in ("token", "client_secret", "bearer", "password"):
        assert word not in lowered
