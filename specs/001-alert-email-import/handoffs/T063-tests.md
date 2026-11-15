# T063 tests: repository secret scan

File: `tests/test_no_secrets.py` (no `app/` changes).

## What the tests assert
- `test_repo_has_no_forbidden_secret_files` / `test_repo_has_no_refresh_token_strings` (both with `no_network`): scan the repository tree excluding `.git`, build artefact directories (`__pycache__`, `.pytest_cache`, `.venv`, `venv`) and `*.pyc` files, and assert no forbidden credential file name (`client_secret*.json`, `token*.json`, `token.bin`) and no realistic-length refresh-token-shaped string is present. Content scan skips household data paths `data/`, `config/needs.yaml`, `config/zone_aliases.yaml` and never reports matched content, only the path.
- `test_detects_forbidden_file_names` (tmp_path): a `client_secret*.json`, `token.json` and `token.bin` created under a temporary root are all detected by the file-name scan.
- `test_detects_refresh_token_shaped_string` (tmp_path): a file containing a runtime-built token-shaped sample with `MIN_TOKEN_BODY` (40) body chars is detected; the assertion/failure message reports only the path and never the matched content.
- `test_short_obviously_fake_token_tolerated` (tmp_path): a runtime-built short fake token (`1//0` + `fake-refresh-token-FOR-TESTS-ONLY`, 33 body chars, < `MIN_TOKEN_BODY`) is not flagged, documenting the length-gate trade-off.

## Implementation notes / decision
- Scanner helpers (`find_forbidden_files`, `find_refresh_token_strings`) live in the test module so they can be exercised against `tmp_path` roots without touching the repository. The refresh-token regex and all samples are built at runtime to avoid literal token-shaped strings in this source file.
- Build artefacts (`__pycache__`, `.pytest_cache`, `.venv`/`venv` dirs and `*.pyc`) are skipped as gitignored, not repository content.
- Realistic-token gate: `MIN_TOKEN_BODY = 40` (named constant). Real Google refresh tokens carry 45+ random body characters; the repository's existing fake test tokens are <= 34 obviously fake body characters. Only tokens with >= 40 body chars of `[A-Za-z0-9_-]` are flagged. Trade-off (documented in code/test): a hypothetical real token with an unusually short body would be missed; short obviously fake tokens are tolerated and token content is never inspected or reported.

## Gates (isolated env under `$env:TEMP\casa-agent`, run from worktree root)
- `python -m compileall -q app tests` — exit 0
- `python -m pytest -q -m "not slow"` — exit 0 (602 passed, 1 skipped, 2 deselected, 1 warning)
- `python tests/fixtures/anonymise_eml.py --check tests/fixtures/emails` — exit 0
- `git diff --name-only main...HEAD` — lists only `tests/test_no_secrets.py` and `specs/001-alert-email-import/handoffs/T063-tests.md`
- `git diff main...HEAD -- requirements.txt` — empty

## Notes
- No pre-existing files (including merged fake test tokens in mailbox tests/handoffs or untracked `__pycache__/*.pyc`) were edited; only `tests/test_no_secrets.py` and this handoff were changed.
