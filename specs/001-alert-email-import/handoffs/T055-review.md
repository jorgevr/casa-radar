# T055 review

**[PASS]**

Scope: `git diff main...HEAD` = `app/mailbox/credentials.py` + `handoffs/T055-dev.md` only. `requirements.txt` untouched, no new dependency, no network calls, no tests edited. Ran with CASA_* pointing to `%TEMP%\casa-agent`: `compileall` OK; `tests/test_mailbox_credentials.py` 4 passed. Manual check: `repr`, `str`, f-string and `%s` of the loaded Secret all give `<redacted>`; `.value` round-trips; `token.bin` written; `delete_token` then `load_refresh_token()` -> `None`; repo-local `CASA_APPDATA` -> `ValueError("app folder must not be inside the repository")`, no token in the message. Matches decisions.md (T055 section; read from `jorgevr/Implementation`): `.value` holder, redacted repr/str, `ValueError` on repo-local path via resolved-path comparison.

## Checked, no defect
- Secrets in errors: every raise is a fixed string (credentials.py:69, 73, 90-96, 111, 135); the file-not-found message includes only the folder path. `from None` suppresses chained context. Nothing is printed or logged.
- Secret (credentials.py:21-39): `__slots__`, redacted `__repr__/__str__/__format__`, `__reduce__` blocks pickling.
- DPAPI (credentials.py:100-122): both blobs hold references to their buffers (`_keep_in`, `_keep_ent`) for the call; output freed in `finally: kernel32.LocalFree(ctypes.cast(out_blob.pbData, ctypes.c_void_p))`; arg order matches `CryptProtectData(in, descr, entropy, reserved, prompt, flags, out)` and `CryptUnprotectData(in, descrOut, entropy, ...)`; failure raises a generic `OSError`. Round trip verified.
- Repo guard (credentials.py:69-72) runs before any write (`_token_path()` before `mkdir`/`write_bytes`).

## Minor notes (non-blocking)
1. credentials.py:125-132, non-Windows `os.open(path, O_WRONLY|O_CREAT|O_TRUNC, 0o600)`: an already-existing `token.json` with looser mode keeps it until the later `os.chmod(path, 0o600)`; a brief window, and the app dir is not created `0o700` (`path.parent.mkdir(parents=True, exist_ok=True)`). Untested on this Windows host. Acceptable for a single-user tool.
2. credentials.py:111 `fn(*args)` passes flags `0`; `CRYPTPROTECT_UI_FORBIDDEN` (0x1) is not set. No prompt struct is given, so no UI appears in practice; setting it would be stricter.
3. credentials.py:119-121 the plaintext `bytes` returned by `string_at` and the `LocalFree`'d buffer are not zeroed; inherent to Python strings, not an issue.
4. Real `%LOCALAPPDATA%\casa-radar` is not refused under test; decisions.md makes that optional ("only if the tests can express it").
5. `app/mailbox/__init__.py` absent (T054's); works as namespace package, correctly not created here.
