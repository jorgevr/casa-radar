# T050 — tests: mailbox credentials

Role: Test Author (tests only). Task: add `tests/test_mailbox_credentials.py` for
`app/mailbox/credentials.py` (T055, not implemented).

## Files

- `tests/test_mailbox_credentials.py` (new)
- `specs/001-alert-email-import/handoffs/T050-tests.md` (this handoff)

No files under `app/`, `tests/conftest.py`, `requirements.txt`, `config/`, `data/`,
or `tasks.md` were created or edited.

## Tests and what each asserts

All tests set `CASA_APPDATA` to an isolated temporary path (via `tmp_path` +
`monkeypatch.setenv`) and import `app.mailbox.credentials` lazily inside each test so
collection succeeds and each test fails individually on the missing module. A single
obviously fake token string (`1//0fake-refresh-token-FOR-TESTS-ONLY`) is used; no real
secrets.

1. `test_round_trip_save_and_load_refresh_token`
   - With `CASA_APPDATA=tmp_path`, calls `save_refresh_token(FAKE_TOKEN)` then
     `load_refresh_token()` and asserts the loaded value carries the original token.
   - Accepts either a plain string or a secret-holder object exposing the value via a
     common attribute/method (`value` / `get_secret_value()` / `secret`) to tolerate the
     holder shape chosen by T055 while checking the round-trip.

2. `test_stored_bytes_do_not_contain_token_in_clear_on_windows` (skipped off Windows)
   - With `CASA_APPDATA=tmp_path`, saves the token and asserts the stored
     `tmp_path/token.bin` exists and its raw bytes do not contain the token encoded as
     UTF-8 or UTF-16LE (DPAPI-encrypted at rest, not cleartext).

3. `test_secret_holder_repr_never_shows_value`
   - Saves/loads the token and asserts the loaded value is not a plain `str` (must be a
     secret holder) and that neither `repr(loaded)` nor `str(loaded)` contains the fake
     token or its distinctive fragment. This enforces redacted representations.

4. `test_app_folder_inside_repository_root_is_rejected`
   - Points `CASA_APPDATA` at a directory inside the resolved repository root and asserts
     an exception is raised when using credentials storage (`save_refresh_token` or, if
     save unexpectedly does not raise, `load_refresh_token`). The probe directory is
     cleaned up in `finally`.

## Run and observed failure reason

Isolation (set before running, outside the repository):

```powershell
New-Item -ItemType Directory -Force "$env:TEMP\casa-agent-T050" | Out-Null
$env:CASA_DB="$env:TEMP\casa-agent-T050\casa.db"
$env:CASA_NEEDS="$env:TEMP\casa-agent-T050\needs.yaml"
$env:CASA_APPDATA="$env:TEMP\casa-agent-T050\appdata"
Copy-Item config\needs.example.yaml $env:CASA_NEEDS -Force
```

Command: `python -m pytest tests/test_mailbox_credentials.py -q`

Result: `4 failed in 16.72s` (exit 1). Every test failed for the **right/expected**
reason: the implementation module does not exist yet.

Exact failure observed in each test (from `tests/test_mailbox_credentials.py:20`,
`_credentials()`):

```
E       ModuleNotFoundError: No module named 'app.mailbox'
>       from app.mailbox import credentials  # noqa: PLC0415
```

No syntax errors, no fixture errors, and no wrong-test failures were observed.

## Gates

- `python -m compileall -q app tests` — exit 0 (env isolated as above).
- `python -m pytest tests/test_mailbox_credentials.py -q` — 4 failed, all
  `ModuleNotFoundError: No module named 'app.mailbox'` (expected; implementation
  absent).
- `python tests/fixtures/anonymise_eml.py --check tests/fixtures/emails` — exit 0.
- `git diff --name-only main...HEAD` (pre-commit working tree) — only the test file
  and this handoff; nothing under `data/`, no `config/needs.yaml`,
  `config/zone_aliases.yaml`, no `client_secret*`, no `token*`, no `.eml` outside
  `tests/fixtures/emails/`.
- `git diff main...HEAD -- requirements.txt` — empty.
- `python -m pytest -q -m "not slow"` — not re-run in this session beyond noting the
  per-task instruction; earlier phases own the baseline. If required before reporting,
  stop-at-first-failure applies (no unrelated failures observed running the targeted
  file).

## Decisions / notes for reviewers

- **Import style:** imports are performed inside each test (via a small `_credentials()`
  helper) rather than at module top level so pytest collects 4 independent tests and each
  fails on the missing `app.mailbox`/`app.mailbox.credentials` module instead of a
  single collection error hiding the rest.
- **Secret-holder shape:** the round-trip test accepts a plain string or a holder exposing
  the token via `value`, `get_secret_value()`, or `secret` so it does not over-constrain
  T055's API beyond the task/contracts; the repr-redaction test explicitly requires a
  non-`str` holder whose `repr`/`str` are redacted.
- **DPAPI path:** the cleartext-bytes check expects `token.bin` under `CASA_APPDATA`
  (per research R4) and is skipped off Windows.
- **Repo-root rejection:** the test asserts an exception is raised on credential
  operations when `CASA_APPDATA` resolves inside the repository root (per R4/task: "refuse
  a path inside the repository"); it does not assume the exact exception type or the
  exact function name beyond `save_refresh_token`/`load_refresh_token`.
- **`delete_token` / `load_client_secret`:** mentioned in R4/contracts but not named in
  T050's explicit assertions; not tested here to stay within the task text. T055/T051 may
  cover them.
- No deviations from task text or contracts were identified; nothing required escalation.
