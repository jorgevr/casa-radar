"""Local storage of mailbox credentials (research R4).

The app folder holds ``client_secret.json`` (copied by the user) and the refresh token:
``token.bin`` (Windows DPAPI, current user) or ``token.json`` (owner-only, not encrypted)
elsewhere. Secrets are wrapped in :class:`Secret`, whose repr/str are redacted.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

REDACTED = "<redacted>"
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_DPAPI_ENTROPY = b"casa-radar-refresh-token"


class Secret:
    """Holds a secret string; never renders it in repr/str/format."""

    __slots__ = ("_value",)

    def __init__(self, value: str) -> None:
        self._value = value

    @property
    def value(self) -> str:
        return self._value

    def __repr__(self) -> str:
        return REDACTED

    def __str__(self) -> str:
        return REDACTED

    def __format__(self, spec: str) -> str:
        return REDACTED

    def __reduce__(self):
        raise TypeError("Secret cannot be pickled")


def app_dir() -> Path:
    """Return the app folder, refusing a location inside the repository."""
    override = os.environ.get("CASA_APPDATA")
    if override:
        base = Path(override)
    else:
        local = os.environ.get("LOCALAPPDATA")
        if not local:
            raise ValueError("LOCALAPPDATA is not set; set CASA_APPDATA to choose the app folder")
        base = Path(local) / "casa-radar"
    resolved = base.resolve()
    if resolved == _REPO_ROOT or _REPO_ROOT in resolved.parents:
        raise ValueError("app folder must not be inside the repository")
    return resolved


def load_client_secret() -> dict:
    """Read ``client_secret.json`` (installed-app format) and return its ``installed`` section."""
    path = app_dir() / "client_secret.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise FileNotFoundError(f"client_secret.json not found in {path.parent}") from None
    except ValueError:
        raise ValueError("client_secret.json is not valid JSON") from None
    installed = data.get("installed") if isinstance(data, dict) else None
    if not isinstance(installed, dict):
        raise ValueError("client_secret.json is not in installed-app format")
    for key in ("client_id", "auth_uri", "token_uri"):
        if not installed.get(key):
            raise ValueError(f"client_secret.json is missing '{key}'")
    return installed


# --- DPAPI (Windows) -------------------------------------------------------------------


def _dpapi(data: bytes, protect: bool) -> bytes:
    import ctypes  # noqa: PLC0415
    from ctypes import wintypes  # noqa: PLC0415

    class DataBlob(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

    def blob(raw: bytes) -> tuple[DataBlob, object]:
        buf = ctypes.create_string_buffer(raw, len(raw))
        return DataBlob(len(raw), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char))), buf

    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    in_blob, _keep_in = blob(data)
    ent_blob, _keep_ent = blob(_DPAPI_ENTROPY)
    out_blob = DataBlob()
    fn = crypt32.CryptProtectData if protect else crypt32.CryptUnprotectData
    args = [ctypes.byref(in_blob)]
    args.append(None)  # description (protect) / description out (unprotect)
    args += [ctypes.byref(ent_blob), None, None, 0, ctypes.byref(out_blob)]
    if not fn(*args):
        raise OSError("Windows DPAPI failed to " + ("protect" if protect else "unprotect") + " the token")
    try:
        return ctypes.string_at(out_blob.pbData, out_blob.cbData)
    finally:
        kernel32.LocalFree(ctypes.cast(out_blob.pbData, ctypes.c_void_p))


def _token_path() -> Path:
    return app_dir() / ("token.bin" if sys.platform == "win32" else "token.json")


def save_refresh_token(token: str | Secret) -> None:
    raw = token.value if isinstance(token, Secret) else token
    path = _token_path()  # validates the folder before anything is written
    path.parent.mkdir(parents=True, exist_ok=True)
    if sys.platform == "win32":
        path.write_bytes(_dpapi(raw.encode("utf-8"), protect=True))
        return
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump({"refresh_token": raw}, fh)
    os.chmod(path, 0o600)


def load_refresh_token() -> Secret | None:
    """Return the stored refresh token as a Secret, or None when none is stored."""
    path = _token_path()
    if not path.exists():
        return None
    if sys.platform == "win32":
        return Secret(_dpapi(path.read_bytes(), protect=False).decode("utf-8"))
    try:
        value = json.loads(path.read_text(encoding="utf-8")).get("refresh_token")
    except (ValueError, AttributeError):
        raise ValueError("token.json is corrupt") from None
    return Secret(value) if isinstance(value, str) and value else None


def delete_token() -> None:
    _token_path().unlink(missing_ok=True)
