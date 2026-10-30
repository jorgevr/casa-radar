"""Console encoding of `import-emails` (follow-up to T019, review finding 3).

On Windows a piped or redirected stdout is cp1252. A subject with characters outside cp1252 must not
lose the summary or turn a completed import into exit 1. Expected totals come from the Phase 3
Independent Test (12 fixtures: 11 imported, 1 rejected) and from the one email built here, not from
running the code. The foreign email is deliberately not an Idealista alert (same idea as T043); it
is built in memory, no alert format is invented.
"""
import io
import sys
from email.message import EmailMessage

import pytest

from app import cli

from .conftest import EMAILS

SUBJECT = "Oferta \u2260 casa \U0001F3E0"  # "Oferta ≠ casa 🏠": neither character exists in cp1252


def _stdout(encoding):
    return io.TextIOWrapper(io.BytesIO(), encoding=encoding, errors="strict", newline="")


def _run(monkeypatch, paths, encoding):
    out = _stdout(encoding)
    monkeypatch.setattr(sys, "stdout", out)
    code = cli.main(["import-emails", *map(str, paths)])
    out.flush()
    return code, out.buffer.getvalue().decode(encoding)


@pytest.fixture
def foreign_eml(tmp_path):
    msg = EmailMessage()
    msg["Subject"] = SUBJECT
    msg["From"] = "ofertas@example.com"
    msg["To"] = "casa@example.com"
    msg["Date"] = "Tue, 27 Oct 2026 10:00:00 +0000"
    msg["Message-ID"] = "<foreign-1@example.com>"
    msg.set_content("Hola, esto no es una alerta.")
    path = tmp_path / "foreign.eml"
    path.write_bytes(bytes(msg))
    return path


def test_cp1252_stdout_unencodable_subject_keeps_summary_and_exit_0(foreign_eml, monkeypatch, no_network):
    code, text = _run(monkeypatch, [foreign_eml], "cp1252")  # must not raise UnicodeEncodeError

    assert code == 0  # a rejected email is not a failure
    assert "1 email: 0 importados, 0 ya procesados, 1 rechazado, 0 fallidos" in text
    assert "RECHAZADO" in text
    assert "Oferta" in text


def test_cp1252_stdout_fixture_folder_totals(monkeypatch, no_network):
    assert len(list(EMAILS.glob("*.eml"))) == 12

    code, text = _run(monkeypatch, [EMAILS], "cp1252")

    # Phase 3 Independent Test: 12 emails: 11 imported, 0 already, 1 rejected, 0 failed
    assert code == 0
    assert "12 emails: 11 importados, 0 ya procesados, 1 rechazado, 0 fallidos" in text


def test_utf8_stdout_keeps_characters_intact(monkeypatch, no_network):
    code, text = _run(monkeypatch, [EMAILS], "utf-8")

    assert code == 0
    # the rejected 2021 fixture's subject starts with an inverted exclamation mark, which must not be degraded
    assert "RECHAZADO 2021-03-10 \u00a1Nuevo piso" in text
