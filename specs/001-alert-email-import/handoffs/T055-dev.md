# T055 dev handoff

## Changed
- New `app/mailbox/credentials.py` (only file of code). No tests edited.
- `app_dir()`: `CASA_APPDATA` or `%LOCALAPPDATA%\casa-radar`; resolved path equal to or inside the repo root -> `ValueError("app folder must not be inside the repository")` (no token in message). Checked before any write.
- `load_client_secret()` returns the `installed` dict of `client_secret.json`; validates client_id/auth_uri/token_uri present.
- `save_refresh_token` (accepts str or Secret) / `load_refresh_token` (returns `Secret` or `None` if absent) / `delete_token`.
  Windows: DPAPI via ctypes -> `token.bin`; elsewhere `token.json`, mode 0600.
- `Secret`: `.value`; `__repr__`/`__str__`/`__format__` return `<redacted>`; not picklable.

## Decisions not covered by docs
- `app/mailbox/__init__.py` does NOT exist in this branch (belongs to T054); `app.mailbox` works as a namespace package, so tests pass. Not created here.
- DPAPI uses a fixed app-specific entropy string (`casa-radar-refresh-token`) as extra binding; it is not a secret.
- `load_refresh_token()` returns None when no token is stored (callers: treat as "not authorised").
- Error messages never include file contents.
- decisions.md (read from jorgevr/Implementation, T055 section): implementation already matches (Secret .value + redacted repr/str; ValueError without secrets for repo-local CASA_APPDATA, resolved-path comparison).

## Reviewer should check
- DPAPI ctypes call signature (CryptProtectData/CryptUnprotectData arg order, LocalFree of output blob) — round trip verified on Windows by tests.
- Non-Windows branch (`token.json`) is untested here (Windows host).

## Gates
- compileall: OK
- tests/test_mailbox_credentials.py: 4 passed
- pytest -m "not slow": 503 passed, 1 skipped, 29 failed — all failures in test_mailbox_gmail.py, test_mailbox_oauth.py, test_sync.py (modules of later tasks T054/T056+ missing).
- anonymise_eml --check: OK (exit 0)
- git diff gates: see below, run before commit.
