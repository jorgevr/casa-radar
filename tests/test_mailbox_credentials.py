"""Credentials storage for mailbox access (T050).

Implementation does not exist yet: each test imports app.mailbox.credentials and
is expected to fail with ModuleNotFoundError/ImportError until T055 lands.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

# Obviously fake token value used only in tests; never a real secret.
FAKE_TOKEN = "1//0fake-refresh-token-FOR-TESTS-ONLY"


def _credentials():
    from app.mailbox import credentials  # noqa: PLC0415

    return credentials


def test_round_trip_save_and_load_refresh_token(tmp_path, monkeypatch):
    """save_refresh_token/load_refresh_token round-trip under CASA_APPDATA=tmp_path."""
    monkeypatch.setenv("CASA_APPDATA", str(tmp_path))
    credentials = _credentials()

    credentials.save_refresh_token(FAKE_TOKEN)
    loaded = credentials.load_refresh_token()

    # The loaded value must carry the original token (possibly wrapped in a
    # Secret holder). Accept either a plain string or an object exposing the
    # token via a common attribute/name while remaining non-leaking in repr.
    if isinstance(loaded, str):
        assert loaded == FAKE_TOKEN
    else:
        value = getattr(loaded, "value", None)
        if value is None and hasattr(loaded, "get_secret_value"):
            value = loaded.get_secret_value()
        if value is None and hasattr(loaded, "secret"):
            value = loaded.secret
        assert value == FAKE_TOKEN


@pytest.mark.skipif(sys.platform != "win32", reason="DPAPI storage applies on Windows")
def test_stored_bytes_do_not_contain_token_in_clear_on_windows(tmp_path, monkeypatch):
    """On Windows the stored bytes do not contain the token in clear (DPAPI)."""
    monkeypatch.setenv("CASA_APPDATA", str(tmp_path))
    credentials = _credentials()

    credentials.save_refresh_token(FAKE_TOKEN)

    token_path = tmp_path / "token.bin"
    assert token_path.exists(), "expected DPAPI token to be stored in token.bin"
    raw = token_path.read_bytes()
    assert FAKE_TOKEN.encode("utf-8") not in raw
    assert FAKE_TOKEN.encode("utf-16-le") not in raw


def test_secret_holder_repr_never_shows_value(tmp_path, monkeypatch):
    """repr() of the secret holder never shows the value."""
    monkeypatch.setenv("CASA_APPDATA", str(tmp_path))
    credentials = _credentials()

    credentials.save_refresh_token(FAKE_TOKEN)
    loaded = credentials.load_refresh_token()

    # A plain string cannot satisfy the "secret holder" redaction requirement;
    # loading must return a holder object whose representations are redacted.
    assert not isinstance(loaded, str), "refresh token must be wrapped in a secret holder"
    for rendered in (repr(loaded), str(loaded)):
        assert FAKE_TOKEN not in rendered
        assert "FAKE-REFRESH-TOKEN" not in rendered


def test_app_folder_inside_repository_root_is_rejected(tmp_path, monkeypatch):
    """App folder is never inside the repository root (assert raises)."""
    credentials = _credentials()
    repo_root = Path(__file__).resolve().parent.parent
    inside_repo = repo_root / ".tmp-casa-appdata-inside-repo"
    inside_repo.mkdir(exist_ok=True)
    try:
        monkeypatch.setenv("CASA_APPDATA", str(inside_repo))
        with pytest.raises(Exception):
            # Any of these operations must refuse a repository-local app folder.
            try:
                credentials.save_refresh_token(FAKE_TOKEN)
            except Exception:
                raise
            # If save did not raise (unexpected), loading must.
            credentials.load_refresh_token()
    finally:
        # Clean up the empty probe directory inside the worktree if it remains.
        try:
            for child in inside_repo.iterdir():
                child.unlink()
            inside_repo.rmdir()
        except OSError:
            pass
