# T053 tests — mailbox sync (Phase 9)

## Files
- `tests/test_sync.py` (new)
- `specs/001-alert-email-import/handoffs/T053-tests.md` (this file)

## Scope and constraints
- Tests only (no `app/`, no `tests/conftest.py`, no `requirements.txt`, no `config/`, no `data/`, no `tasks.md`).
- Offline: every case uses the `no_network` fixture (socket connect/create refused). `FakeMailSource` serves in-memory fixture bytes; no Google, no browser, no real sync/mailbox-setup. Fake token strings are obviously fake (`ya29.FAKE-*`), never real secrets.
- Expected values taken from the task/contracts (12 fixtures, 11 imported / 1 rejected for the 2021 unsupported alert; 30-day first window FR-027; out-of-date after failed attempt or 30 minutes without success FR-028), not from running production code.

## What each test asserts
| Test | Asserts |
|---|---|
| `test_malformed_rules_import_as_unknown_and_load_once` | With a malformed `alert_categories.yaml`, a sync still imports messages as category `unknown`, `import_runs.error` starts with `ValueError: ` and status `ok`, and the rules file is read once per run (count `load_rules` calls). |
| `test_first_sync_uses_30_day_window_and_skips_older` | First sync lists with `after == today - 30 days` (FR-027) and does not fetch/store messages dated older than that window. |
| `test_second_sync_fetches_nothing_already_stored` | Second sync over the same mailbox finds nothing already stored (FR-026): `n_found==0`, `n_imported==0`, `n_already==0`. |
| `test_new_message_imported_and_counted_only_once` | A message newly present after a prior sync is found on the next sync; if its content/email identity was already imported (e.g. same bytes, different mailbox id), it is counted as `already` (not re-imported). |
| `test_same_email_file_then_mailbox_already_processed` | Same email first imported from a file, then seen from the mailbox, is reported already processed (`n_found==1, n_already==1, n_imported==0`). |
| `test_interruption_after_n_keeps_them_and_resumes` | If the source raises mid-way (`SourceUnavailable` on the 4th fetch), the first 3 remain stored/processed; a later healthy sync resumes, imports the rest, and the total stored mailbox messages equal 12. |
| `test_auth_revoked_sets_state_and_pauses` | `AuthRevoked` (e.g. `invalid_grant`) sets `mailbox_state.auth_state='revoked'` and `auto_sync='paused_auth'` (FR-029, US1-8). |
| `test_auth_revoked_scheduler_skips` | A scheduled sync with `auth_state='revoked', auto_sync='paused_auth'` does not list the mailbox and returns `n_found==0`. |
| `test_folder_not_found_reports_name_and_reads_nothing` | `FolderNotFound` stops with an error containing `carpeta` and the label name (`Idealista`), and no emails are read/stored. |
| `test_source_unavailable_records_error_and_schedule_continues` | `SourceUnavailable` records `last_error`/`last_attempt_status='failed'` but leaves `auth_state='valid'` and `auto_sync='on'` so the schedule continues. |
| `test_second_concurrent_sync_refused` | A second sync while one is running is refused (FR-025); asserted by an error whose text indicates sync already running. |
| `test_out_of_date_after_failure_or_stale_success` | `alerts_sync.out_of_date(state, now)` is true after a failed attempt or when last success is > 30 minutes ago, false when last success is recent and ok (FR-028). |
| `test_thousand_message_backlog_under_ten_minutes` (`@pytest.mark.slow`) | A `FakeMailSource` backlog of 1,000 messages (fixture bytes, distinct ids) syncs with `n_found==1000` in < 600 s (SC-010). |

## Failure reason observed (right reason)
Ran (isolated env `CASA_DB/NEEDS/APPDATA` under `$env:TEMP\casa-agent-T053`, needs copied from `config/needs.example.yaml`):
`python -m pytest tests/test_sync.py -q` → **13 failed in 33.81s**. Every test fails with
`ImportError: cannot import name 'alerts_sync' from 'app'` (raised from the lazy helper importing `app.alerts_sync`).
This is the expected/accepted failure because `app/mailbox/*` and `app/alerts_sync.py` do not exist yet (implementation out of scope). Imports are lazy (inside helpers/tests) so each test fails individually rather than one collection error.

## Decisions / assumptions the docs do not fully pin down (reviewer notes)
- **Sync API shape:** tests assume `app.alerts_sync.sync(conn, source, kind=...) -> run summary dict` (with at least `run_id`, `n_found`, `n_imported`, `n_already`, `n_rejected`) and `app.alerts_sync.out_of_date(state, now) -> bool`, consistent with T058/research R6 and how `alerts.import_paths` returns summaries. If the implementation names/signatures differ, these tests will need to be adapted by the implementer (I did not guess stubs).
- **Mailbox state seeding:** tests insert a `mailbox_state` row directly for setup (label/account/auth/auto_sync/backfill). If sync requires different initial state handling, adjust fixtures accordingly.
- **`test_new_message_imported_and_counted_only_once`:** adds a second mailbox id carrying the same raw bytes as an already-imported fixture; asserts it is found but `already` (dedupe by content/email_id per FR-026 / data-model uniqueness), not `imported`. If the chosen "new message" must be content-distinct, the expected counts would change to `n_imported==1`.
- **Concurrent refusal:** asserted via a raised exception whose message contains "sync" and ("running"/"ejec"/"progreso") to tolerate the exact Spanish/English wording chosen by the implementation.
- **`FolderNotFound` error text:** asserted to include `carpeta` and the label name (task states error "carpeta <nombre> no encontrada"); storage checked via `last_error` and no `alert_emails` rows.

## Gates run
- `python -m compileall -q app tests` — exit 0
- `python tests/fixtures/anonymise_eml.py --check tests/fixtures/emails` — exit 0
- `git diff main...HEAD -- requirements.txt` — empty (after commit)
- `git diff --name-only main...HEAD` — only `specs/001-alert-email-import/handoffs/T053-tests.md` and `tests/test_sync.py` (after commit)
