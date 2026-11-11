"""Credentials storage for mailbox access (T050).

Implementation does not exist yet: each test imports app.mailbox.credentials and
is expected to fail with ModuleNotFoundError/ImportError until T055 lands.

Contract choice for T055 (documented per review F1/F2): load_refresh_token()
returns a redacted Secret holder (never a str) exposing the token value via the
.value attribute. Refusing a CASA_APPDATA path inside the repository root raises
ValueError (review F4).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Obviously fake token value used only in tests; never a real secret.
FAKE_TOKEN = "1//0fake-refresh-token-FOR-TESTS-ONLY"


def _credentials():
    from app.mailbox import credentials  # noqa: PLC0415

    return credentials


def test_round_trip_save_and_load_refresh_token(tmp_path, monkeypatch, no_network):
    """save_refresh_token/load_refresh_token round-trip under CASA_APPDATA=tmp_path."""
    monkeypatch.setenv("CASA_APPDATA", str(tmp_path))
    credentials = _credentials()

    credentials.save_refresh_token(FAKE_TOKEN)
    loaded = credentials.load_refresh_token()

    # load_refresh_token() returns a Secret holder (never a str) exposing the
    # token via .value (deterministic accessor chosen for T055).
    assert not isinstance(loaded, str), "refresh token must be wrapped in a secret holder"
    assert loaded.value == FAKE_TOKEN


@pytest.mark.skipif(sys.platform != "win32", reason="DPAPI storage applies on Windows")
def test_stored_bytes_do_not_contain_token_in_clear_on_windows(tmp_path, monkeypatch, no_network):
    """On Windows the stored bytes do not contain the token in clear (DPAPI)."""
    monkeypatch.setenv("CASA_APPDATA", str(tmp_path))
    credentials = _credentials()

    credentials.save_refresh_token(FAKE_TOKEN)

    token_path = tmp_path / "token.bin"
    assert token_path.exists(), "expected DPAPI token to be stored in token.bin"
    raw = token_path.read_bytes()
    assert FAKE_TOKEN.encode("utf-8") not in raw
    assert FAKE_TOKEN.encode("utf-16-le") not in raw


def test_secret_holder_repr_never_shows_value(tmp_path, monkeypatch, no_network):
    """repr() of the secret holder never shows the value."""
    monkeypatch.setenv("CASA_APPDATA", str(tmp_path))
    credentials = _credentials()

    credentials.save_refresh_token(FAKE_TOKEN)
    loaded = credentials.load_refresh_token()

    assert not isinstance(loaded, str), "refresh token must be wrapped in a secret holder"
    assert loaded.value == FAKE_TOKEN
    for rendered in (repr(loaded), str(loaded)):
        assert FAKE_TOKEN not in rendered
        # Fragment that actually appears in the fake token, to catch partial leaks.
        assert "refresh-token" not in rendered


def test_app_folder_inside_repository_root_is_rejected(tmp_path, monkeypatch, no_network):
    """App folder inside the repository root is refused and nothing is written there."""
    credentials = _credentials()
    repo_root = Path(__file__).resolve().parent.parent
    inside_repo = repo_root / ".tmp-casa-appdata-inside-repo"
    inside_repo.mkdir(exist_ok=True)
    try:
        monkeypatch.setenv("CASA_APPDATA", str(inside_repo))
        # The first credentials operation must refuse the repository-local path.
        with pytest.raises(ValueError, match=r"(?i)repository|repo|inside"):
            credentials.save_refresh_token(FAKE_TOKEN)
        # Refusal must not write anything inside the repository.
        assert list(inside_repo.iterdir()) == []
    finally:
        # Clean up the empty probe directory inside the worktree if it remains.
        for child in list(inside_repo.iterdir()):
            if child.is_dir():
                child.rmdir()
            else:
                child.unlink()
        inside_repo.rmdir()

