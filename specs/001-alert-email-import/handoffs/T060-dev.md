# T060 dev handoff — mailbox-setup and sync CLI

**File changed:** `app/cli.py` only (plus this handoff). Tests untouched.

## What changed
- New commands `mailbox-setup [--label NAME]` and `sync [--wait]`; module docstring usage list updated.
- Seams as pinned by the tests: `SYNC_WAIT_TIMEOUT_SECONDS` (600), `_clock`, `_sleep`, `_run_sync`,
  `_make_source`, `_authorize`, `_stdin_is_tty`, `_run_detail`. `httpx`/`oauth`/`gmail`/`alerts_sync` are imported lazily
  inside the seams/commands, so existing commands are unaffected.
- `sync`: running = `mailbox_state.running_run_id` whose `import_runs.status == 'running'` (stale ids ignored) or
  `sync()` returning `already_running`. Without `--wait` → exit 3; with `--wait` polls (`SYNC_WAIT_POLL_SECONDS`=5) until
  clear or `SYNC_WAIT_TIMEOUT_SECONDS`, then exit 3 without syncing. Exit 0 / 1 (`n_failed > 0` in the stored run) /
  2 (status `error`) / 3. Output = `format_import_summary(_run_detail(...))` + `Última sincronización correcta: YYYY-MM-DD HH:MM`.
- `_run_detail` copies the logic of `app.main.run_detail` (main.py not imported or edited).
- `mailbox-setup`: no `--label` and non-tty stdin → nothing authorised, Spanish message asking for `--label NOMBRE`, exit 2.
  With tty it prompts for the label. Flow: authorise → source → account → `resolve_folder` → store provider/account/
  label_name/label_id/auth_state=valid/auto_sync=on and clear last_error. Prints the three contract lines.

## Decisions not covered by docs
- Error output goes to stderr, in fixed Spanish text per error code; exception messages are never printed
  (unexpected setup errors print only the class name). `mailbox_state.last_error` is not printed (the tests plant secrets there).
- The printed account is shown only if it looks like a bare e-mail address, otherwise `desconocida`
  (the test plants a secret in `account()`); the same validated value is stored.
- `sync` with no `mailbox_state` row → exit 2 with "ejecuta mailbox-setup".
- `sync` where the stored run cannot be found → message and exit 1.
- `mailbox-setup` sets `auto_sync='on'` (same as the web authorise flow in main.py), overriding a prior pause.
- `_make_source` creates an `httpx.Client` per call and does not close it (short-lived process).

## Reviewer checks
- `_run_detail` duplicates `app.main.run_detail` (main.py is not mine); keep them in sync or share later.
- The poll interval constant (5 s) is not pinned by tests.

## Gates
- compileall: pass. `tests/test_cli_mailbox.py`: 21 passed.
- `pytest -m "not slow"`: 593 passed, 1 skipped, 2 deselected. anonymise_eml --check: clean. `git diff --name-only main...HEAD`: no data/, config/needs.yaml, zone_aliases.yaml, secrets or stray .eml. requirements.txt diff: empty.
