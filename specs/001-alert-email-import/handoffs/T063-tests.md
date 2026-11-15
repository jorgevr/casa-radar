# T063 tests: repository secret scan

File: `tests/test_no_secrets.py` (new; no `app/` changes).

## What the tests assert
- `test_repo_has_no_forbidden_secret_files` / `test_repo_has_no_refresh_token_strings` (both with `no_network`): scan the repository tree excluding `.git` and assert no forbidden credential file name (`client_secret*.json`, `token*.json`, `token.bin`) and no string shaped like a Google refresh token (`1//0...`) is present. Content scan skips household data paths `data/`, `config/needs.yaml`, `config/zone_aliases.yaml` and never reports the matched content, only the path.
- `test_detects_forbidden_file_names` (tmp_path): a `client_secret*.json`, `token.json` and `token.bin` created under a temporary root are all detected by the file-name scan.
- `test_detects_refresh_token_shaped_string` (tmp_path): a file containing a runtime-built token-shaped sample (assembled at runtime so this test source contains no literal token-shaped string) is detected; the assertion/failure message reports only the path and never the matched content.

## Implementation notes
- Scanner helpers (`find_forbidden_files`, `find_refresh_token_strings`) live in the test module so they can be exercised against `tmp_path` roots without touching the repository. The refresh-token regex and the synthetic sample are built at runtime (`"".join(["1", "/", "/", "0"]) + ...`) to avoid the test file self-matching.

## Gate results (isolated env under `$env:TEMP\casa-agent`)
- `python -m compileall -q app tests` — exit 0.
- `python -m pytest -q -m "not slow"` — exit 1: `tests/test_no_secrets.py::test_repo_has_no_refresh_token_strings` FAILED (reports token-shaped strings in pre-existing worktree files: `specs/001-alert-email-import/handoffs/T050-tests.md`, `T059-tests.md`, `tests/test_api_mailbox.py`, `tests/test_cli_mailbox.py`, `tests/test_mailbox_credentials.py`, `tests/test_mailbox_oauth.py` and their `tests/__pycache__/*.pyc`). 600 passed, 1 skipped, 2 deselected, 1 warning. The tmp_path detection tests pass, proving the scan fails when a forbidden name or `1//0`-shaped string is present; a tree without those pre-existing strings would pass the repo scan.
- `python tests/fixtures/anonymise_eml.py --check tests/fixtures/emails` — exit 0.
- `git diff main...HEAD -- requirements.txt` — empty.

## Decisions / reviewer notes
- The task states "must pass on a clean tree"; this worktree contains pre-existing token-shaped fixture strings in earlier mailbox tasks and handoffs, so the repo-wide content scan correctly flags them. I did not modify those files (outside this task's scope).
- Exclusions: only `.git` is excluded from traversal per the task; `__pycache__` bytecode files are scanned (and were flagged where they embed the same strings). Household data paths `data/`, `config/needs.yaml`, `config/zone_aliases.yaml` are never read. No matched secret content is printed or included in failure messages (path only).
