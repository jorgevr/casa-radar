# T050 — tests: mailbox credentials

Role: Test Author (tests only). Task: add `tests/test_mailbox_credentials.py` for
`app/mailbox/credentials.py` (T055, not implemented).

## Files

- `tests/test_mailbox_credentials.py`
- `specs/001-alert-email-import/handoffs/T050-tests.md` (this handoff)

No files under `app/`, `tests/conftest.py`, `requirements.txt`, `config/`, `data/`,
or `tasks.md` were created or edited. `handoffs/T050-review.md` was not edited or deleted.

## Tests and what each asserts

All tests request the `no_network` fixture, set `CASA_APPDATA` to an isolated temporary
path (via `tmp_path` + `monkeypatch.setenv`), and import `app.mailbox.credentials`
lazily inside each test so collection succeeds and each test fails individually on the
missing module. A single obviously fake token string
(`1//0fake-refresh-token-FOR-TESTS-ONLY`) is used; no real secrets.

1. `test_round_trip_save_and_load_refresh_token`
   - With `CASA_APPDATA=tmp_path`, calls `save_refresh_token(FAKE_TOKEN)` then
     `load_refresh_token()`.
   - Asserts `load_refresh_token()` returns a Secret holder (not a `str`) and that the
     token is exposed via the deterministic `.value` accessor:
     `loaded.value == FAKE_TOKEN`.

2. `test_stored_bytes_do_not_contain_token_in_clear_on_windows` (skipped off Windows)
   - With `CASA_APPDATA=tmp_path`, saves the token and asserts the stored
     `tmp_path/token.bin` exists and its raw bytes do not contain the token encoded as
     UTF-8 or UTF-16LE (DPAPI-encrypted at rest, not cleartext).

3. `test_secret_holder_repr_never_shows_value`
   - Saves/loads the token and asserts the loaded value is not a plain `str`, that
     `loaded.value == FAKE_TOKEN`, and that neither `repr(loaded)` nor `str(loaded)`
     contains the full token or the fragment `refresh-token` that actually appears in it.

4. `test_app_folder_inside_repository_root_is_rejected`
   - Points `CASA_APPDATA` at a directory inside the resolved repository root and asserts
     the first credentials operation (`save_refresh_token`) raises
     `ValueError` with a message matching `repository|repo|inside`.
   - Asserts refusal writes nothing inside that repository directory
     (`list(inside_repo.iterdir()) == []`). The probe directory is cleaned up in `finally`.

## Contract choices for T055 (deterministic, documented for review F1/F2/F4)

- **Secret holder / accessor:** `load_refresh_token()` returns a redacted Secret holder
  (never a `str`) exposing the token value via the `.value` attribute.
- **Repo-root refusal:** refusing a `CASA_APPDATA` path inside the repository root raises
  `ValueError` (message indicating the repository) on the first credentials operation and
  must not write anything inside the repository. This specific type/match is a
  deterministic test choice recorded here for T055 to satisfy; the task text required a
  raise but did not name the exception type.

## Review iteration 1 (addressing `handoffs/T050-review.md`)

- **F1:** removed `str`/`value`/`get_secret_value`/`secret` probing; round-trip asserts
  holder `.value == FAKE_TOKEN` only.
- **F2:** tests 1 and 3 are consistent: `load_refresh_token()` returns a holder, never a
  `str`.
- **F3:** replaced the dead `"FAKE-REFRESH-TOKEN"` assertion with `"refresh-token"` (a
  fragment that actually appears in `FAKE_TOKEN`).
- **F4:** replaced broad `pytest.raises(Exception)`/no-op inner try with
  `pytest.raises(ValueError, match=...)` on the first operation (`save_refresh_token`) and
  asserted `list(inside_repo.iterdir()) == []` after refusal.
- **F5:** all tests request the `no_network` fixture.

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

Result: `4 failed` (exit 1). Every test failed for the **right/expected** reason: the
implementation module does not exist yet (accepted for this phase).

Exact failure observed in each test (from `tests/test_mailbox_credentials.py`,
`_credentials()`):

```
E       ModuleNotFoundError: No module named 'app.mailbox'
>       from app.mailbox import credentials  # noqa: PLC0415
```

No syntax errors, no fixture errors, and no wrong-test failures were observed.

## Gates

- `python -m compileall -q app tests` — exit 0 (env isolated as above).
- `python -m pytest tests/test_mailbox_credentials.py -q` — 4 failed, all
  `ModuleNotFoundError: No module named 'app.mailbox'` (expected; implementation absent).
- `python tests/fixtures/anonymise_eml.py --check tests/fixtures/emails` — exit 0.
- `git diff --name-only main...HEAD` — only `tests/test_mailbox_credentials.py` and
  `specs/001-alert-email-import/handoffs/T050-tests.md`; nothing under `data/`, no
  `config/needs.yaml`, `config/zone_aliases.yaml`, no `client_secret*`, no `token*`, no
  `.eml` outside `tests/fixtures/emails/`.
- `git diff main...HEAD -- requirements.txt` — empty.

## Notes for reviewers

- **Import style:** lazy import inside each test keeps 4 independent failures on the
  missing module rather than a single collection error.
- **DPAPI path:** expects `token.bin` under `CASA_APPDATA` (per research R4), skipped off
  Windows.
- **`delete_token` / `load_client_secret`:** mentioned in R4/contracts but not named in
  T050's explicit assertions; not tested here to stay within the task text.

