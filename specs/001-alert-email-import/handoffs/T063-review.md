# T063 review

**Verdict: [PASS]** (with stated residual risk)

Run with isolation env vars set (CASA_DB/NEEDS/APPDATA under `%TEMP%\casa-agent`): `python -m pytest -q tests/test_no_secrets.py` → 5 passed.
`git diff --name-only main...HEAD` lists only `tests/test_no_secrets.py` and `specs/001-alert-email-import/handoffs/T063-tests.md` (this review file is added on top).

## 1. Scan walks the tree; detection tests exercise it — [PASS]
- `tests/test_no_secrets.py:59` `for dirpath, dirnames, filenames in os.walk(root):` and `:73` do real recursive walks; `:60`/`:74` prune only `SKIP_DIR_NAMES`.
- `:115-120` `test_detects_forbidden_file_names` creates `client_secret_desktop.json`, `token.json`, `token.bin` in `tmp_path` and asserts the exact set is found via `find_forbidden_files(tmp_path)` — same function the repo-wide test uses (`:108`).
- `:123-137` `test_detects_refresh_token_shaped_string` writes a token-shaped string, asserts `found == [target]`, and goes through `_assert_no_secrets` — the real assertion path.
- Minor: nested-directory detection is not tested directly (all positive samples sit at the tmp root). os.walk recursion is straightforward, so not blocking.
- Minor: `_assert_no_secrets` (`:96`) is used only by the detection test; the two repo-wide tests (`:108`, `:111`) call the finders directly, so their messages are bare list reprs. Those reprs contain paths only, never content.

## 2. MIN_TOKEN_BODY=40 and skip list — [PASS], residual risk below
- `:23` `MIN_TOKEN_BODY = 40`, regex `:36` `r"[A-Za-z0-9_\-]{" + str(MIN_TOKEN_BODY) + r",}"`.
- I measured existing merged fakes in the tree (body length after the `1//0` prefix): `tests/test_cli_mailbox.py:33` = 34, `tests/test_mailbox_credentials.py:20` = 33, `handoffs/T050-tests.md:20` = 33, others 6–15. All < 40, so they are tolerated without editing those tests. A threshold without it would fail the repo-wide test.
- Real Google refresh tokens are `1//0` + ~43–100+ chars, so the 40 gate catches realistic tokens.
- Skips: `:16` `SKIP_DIR_NAMES = {".git", "__pycache__", ".pytest_cache", ".venv", "venv"}` and `:17` `SKIP_FILE_SUFFIXES = (".pyc",)`. These are gitignored build/venv artefacts, not repository content; acceptable. Note the skip applies to any directory with those names anywhere in the tree (a committed `venv/` would also be skipped) and the filename scan (`:63`) also skips `*.pyc`.
- **Residual risk, stated plainly:** (a) a genuine refresh token with a body of 39 or fewer characters is not detected; (b) a token split across lines/escaped or inside a binary/non-UTF-8 file is only partly covered (`:90` decodes with `errors="ignore"`, which can drop bytes); (c) the filename scan (`:65`) still catches the credential files by name regardless of content, so the main real-world leak (a committed `token.json` / `client_secret*.json`) is not weakened by the length gate; (d) a deliberate fake token ≥40 chars anywhere in the repo will fail the test, forcing authors to shorten it.
- This weakens the literal wording ("strings shaped like 1//0...") but the weakening is documented in comments (`:19-22`, `:141-144`) and in the handoff, and is the minimum needed given the constraint not to edit merged tests. Acceptable; the user may want to be aware of it.

## 3. Hygiene — [PASS]
- Messages never print matched content: `:98-100` and `:102-104` join only `str(p.relative_to(root))`. `:135` asserts `sample not in msg`.
- No literal token-shaped string in the file: grep for `1//0` in `tests/test_no_secrets.py` returns 0 hits; the prefix is built with `"".join(["1", "/", "/", "0"])` at `:36`, `:124`, `:146`.
- Household data not read: `:26-30` `SKIP_CONTENT_PATHS = (Path("config/needs.yaml"), Path("config/zone_aliases.yaml"))`, `SKIP_CONTENT_DIRS = (Path("data"),)`; `:81` `if _is_forbidden_name(name) or _should_skip_content(rel): continue` happens before `read_bytes()` (`:84`). `_should_skip_content` (`:50-54`) checks `d in rel.parents` correctly for `data/**`. Note filenames inside `data/` are still checked by `find_forbidden_files` (names only, no reading), which is desired.
- Forbidden-named files are also not read (`:81`), good.
- Offline: all 5 tests take the `no_network` fixture; the file imports only `fnmatch, os, re, pathlib`; no network use.
- No new dependency (`git diff main...HEAD -- requirements.txt` empty).
- No weakened assertions: tests are new (diff shows only additions); the added `test_short_obviously_fake_token_tolerated` (`:140-150`) documents the trade-off with `assert len(fake_body) < MIN_TOKEN_BODY`.
