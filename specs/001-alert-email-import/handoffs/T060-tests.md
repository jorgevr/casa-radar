# T060 tests handoff — mailbox-setup and sync CLI

**Author:** test author (tests only). **Commit:** `T060: tests for mailbox-setup and sync CLI`.
**File:** `tests/test_cli_mailbox.py` (new). No files under `app/` were created or edited.

## How the tests fail now (right reason)

Run after merge of `jorgevr/Implementation` with isolation env vars set
(`CASA_DB/CASA_NEEDS/CASA_APPDATA` under a temp folder, `needs.example.yaml` copied to `CASA_NEEDS`):
`python -m pytest -q tests/test_cli_mailbox.py` → **19 failed, 2 passed** (not syntax errors).
Failures are missing sub-commands/behaviour and missing seams: `argparse`/command handling
for `mailbox-setup`/`sync` is absent or incomplete and the module-level seams below do not
exist yet, so tests fail with `AttributeError` on the missing seam, or assertion failures
showing the commands/output are not implemented. `python -m compileall -q tests/test_cli_mailbox.py` is clean.

## Chosen seams (exact names/signatures in `app.cli`, module-level)

The developer must implement these so tests can monkeypatch them (no real OAuth, source,
sync, clock or sleep). Defaults suggested in parentheses:

- `SYNC_WAIT_TIMEOUT_SECONDS = 600` — named constant, default 10 minutes (not an inline
  literal). `sync --wait` timeout: on timeout exit 3 and never start a sync.
- `_clock() -> datetime` — current time (`datetime.now()`); faked in `--wait` tests.
- `_sleep(seconds) -> None` — polling sleep (`time.sleep`); faked so tests never really sleep.
- `_run_sync(conn, source, kind="sync_manual") -> dict` — runs one sync; default
  `app.alerts_sync.sync(conn, source, kind)`. Faked to control the result and count calls.
- `_make_source(conn, state) -> MailSource` — builds the configured mailbox source for
  sync/setup (reads state/credentials as needed). Faked; never contacts Google.
- `_authorize() -> None` — runs the OAuth authorisation flow (e.g. `app.mailbox.oauth.authorize`);
  faked so nothing is authorised/opened for real.
- `_stdin_is_tty(stream) -> bool` — default `stream.isatty()`; faked to simulate an
  interactive vs non-interactive stdin for `mailbox-setup` without `--label`.
- `_run_detail(conn, run_id) -> dict` — rebuilds the run summary for a stored import run
  (the same data the runs API / `import-emails` use: `problems`, `notices`, and the
  `n_*`/listing counts) so `format_import_summary(detail)` produces the contract summary.
  Default may mirror `app.main.run_detail` / the `GET /api/runs/{id}` shape.

These leave `main(argv)` behaviour for existing commands unchanged (only new subparsers
`mailbox-setup` and `sync` are added).

## What each test asserts

### `mailbox-setup` (class `TestMailboxSetup`)

1. **`test_with_label_authorises_resolves_stores_and_prints`** — with `--label NAME`: calls
   the (faked) `_authorize()`, resolves the label through the (faked) source
   (`resolve_folder("Idealista") -> "Label_12"`), stores `label_name`/`label_id` in
   `mailbox_state`, prints the three Spanish contract lines
   (`Cuenta: usuario@gmail.com`, `Carpeta: Idealista (id Label_12)`,
   `Permiso: solo lectura de Gmail, revocable en myaccount.google.com/permissions`), exit 0.
   No secret leaks.
2. **`test_without_label_noninteractive_refuses_and_does_not_authorise`** — without `--label`
   and non-interactive stdin (`_stdin_is_tty` false): `_authorize()` NOT called, a Spanish
   message asking for `--label NOMBRE` printed, exit 2, no label guessed/stored (pre-existing
   state unchanged).
3. **`test_without_label_interactive_prompts_and_continues`** — without `--label` and
   interactive stdin (`_stdin_is_tty` true, input provides `Idealista`): prompts for the label,
   authorises, resolves, stores and succeeds (exit 0).
4. **`test_setup_source_errors_exit_2_spanish_no_secrets`** (parametrised over `AuthRevoked`,
   `FolderNotFound`, `SourceUnavailable`, each carrying planted fake token/secret strings) —
   during setup: Spanish error message, exit 2, no traceback, nothing sensitive printed.
5. **`test_setup_never_prints_secrets_on_success`** — plants fake token/secret in the source
   data; asserts they appear in neither stdout nor stderr.

### `sync` (class `TestSync`)

6. **`test_ok_no_failed_prints_summary_and_last_success_exit_0`** — ok run, no failed email:
   prints the summary rebuilt from the stored import run via `format_import_summary` (run read
   by `run_id`; `31 emails: 26 importados, 1 ya procesado, 3 rechazados, 0 fallidos` and
   `anuncios: 12 nuevos, 3 actualizados (2 cambios de precio)`) then
   `Última sincronización correcta: <time>` (from `mailbox_state.last_success_at`, formatted as
   in the contract e.g. `2026-10-28 11:45`), exit 0.
7. **`test_failed_email_in_run_exits_1_with_problem_lines`** — a failed email in the run:
   `FALLO` problem line present (reason from the stored run/email outcomes), exit 1.
8. **`test_sync_status_error_exits_2_spanish_no_traceback_no_secrets`** (parametrised over
   `auth_revoked`, `folder_not_found`, `source_unavailable`) — sync status `error`: exit 2 with a
   Spanish error line, no traceback, no secrets (even if `mailbox_state.last_error` contains
   planted strings, output must not leak them).
9. **`test_already_running_returned_by_sync_exits_3_without_second_sync`** — `_run_sync`
   returns `status == "already_running"`: exit 3 immediately, sync not started a second time.
10. **`test_running_run_id_set_exits_3_immediately_and_sync_not_started`** — `mailbox_state.running_run_id`
    points at an `import_runs` row with `status == "running"`: without `--wait` exit 3
    immediately and `_run_sync` never called.
11. **`test_wait_polls_until_clears_then_runs_and_exits_per_result`** — `--wait`: polls until
    the running state clears (fake `_clock`/`_sleep`, no real sleeping; the test clears the
    running state during polling), then runs the sync and exits per its result (0 here).
12. **`test_wait_timeout_exits_3_and_never_starts_sync`** — `--wait` timeout: `SYNC_WAIT_TIMEOUT_SECONDS`
    monkeypatched small, fake clock crosses it → exit 3 and `_run_sync` never started.
13. **`test_stale_running_run_id_not_running_does_not_count_as_running`** — stale
    `running_run_id` whose import run status is NOT `running` (e.g. `failed`): does not count as
    running, sync proceeds normally (exit 0).

### General (class `TestGeneral`)

14. **`test_existing_commands_and_exit_codes_unchanged`** — `categories` still parses/runs;
    `import-emails` exit code unchanged (rejected-only foreign `.eml` → 0).
15. **`test_unknown_flags_rejected_for_new_commands`** — unknown flags rejected for
    `mailbox-setup` and `sync` (argparse exit 2).
16. **`test_commands_appear_in_module_docstring_usage`** — `mailbox-setup` and `sync` appear in
    `cli.__doc__` / usage list.

## Choices where the contract is silent

- **`sync` output source:** per decisions, the summary is rebuilt from the stored import run
  read by `run_id` (`_run_detail`) and printed with `format_import_summary`, followed by
  `Última sincronización correcta: <time>`. Tests accept `last_success_at` formatted as
  `YYYY-MM-DD HH:MM` (contract example) or with the `T` separator, to avoid pinning a
  formatting detail not stated beyond the example.
- **`sync` on source `error`:** tests assert exit 2, a Spanish error line and no
  traceback/secrets. The exact error text is left to the implementation as long as it is
  Spanish and secret-free (it may come from `mailbox_state.last_error` or a mapping of the
  error code).
- **"Running" detection:** as decided — `_run_sync` returning `already_running` OR
  `mailbox_state.running_run_id` set with that `import_runs.status == "running"`. A stale id
  whose run is not `running` is ignored.
- **`mailbox-setup` state row:** tests expect `label_name`/`label_id` stored in
  `mailbox_state` (creating the row with `INSERT OR IGNORE INTO mailbox_state(id) VALUES(1)`
  when needed); the CLI should ensure a state row exists.
- **Interactive prompt / `--wait` poll interval:** exact prompt text and poll interval not
  pinned beyond the specified behaviour.

## Decisions not covered by docs (followed from `decisions.md` T060)

- Named timeout constant `SYNC_WAIT_TIMEOUT_SECONDS` (default 600). Timeout → exit 3, never
  starts a sync. Stale `running_run_id` must not block forever.
- `sync` exit codes 0/1/2/3 as decided. Rebuild summary from stored run by `run_id`.
- `mailbox-setup` without `--label` and non-interactive stdin: authorise nothing, Spanish
  message asking for `--label NOMBRE`, exit 2, never guess a label.
- Secrets never printed; tests never open a browser or contact Google.

## Files

- `tests/test_cli_mailbox.py` — new (this task, tests only).
- `specs/001-alert-email-import/handoffs/T060-tests.md` — this handoff.
