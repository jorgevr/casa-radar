# T053 tests — mailbox sync (Phase 9), review iteration 1

## Files
- `tests/test_sync.py`
- `specs/001-alert-email-import/handoffs/T053-tests.md` (this file)

## Scope and constraints
- Tests only (no `app/`, no `tests/conftest.py`, no `requirements.txt`, no `config/`, no `data/`, no `tasks.md`). `T053-review.md` not edited.
- Offline: every case uses the `no_network` fixture (socket connect/create refused). `FakeMailSource` serves in-memory bytes (real fixture bytes and, where needed, in-memory copies with a unique `Message-ID` for content-distinct messages); no Google, no browser, no real sync/mailbox-setup. No secrets/tokens.
- Expected values taken from the task/contracts (12 fixtures, 11 imported / 1 rejected for the 2021 unsupported alert; 30-day first window FR-027; out-of-date after a failed attempt or 30 minutes without success FR-028), not from running production code.

## What each test asserts
| Test | Asserts |
|---|---|
| `test_malformed_rules_import_as_unknown_and_load_once` | With a malformed `alert_categories.yaml`, sync imports as category `unknown`, `import_runs.error` starts with `ValueError: ` and status `ok`, rules file read once per run, and exactly `IMPORTED` rows are stored as `unknown`. |
| `test_first_sync_uses_30_day_window_sets_backfill_and_skips_older` | With `mailbox_state.backfill_from=None`, sync lists with `after == today - 30 days`, sets `backfill_from` to that date, and does not fetch/store a message older than the window (fake ignores `after` in listing to prove sync enforces the window). |
| `test_second_sync_fetches_nothing_already_stored` | After a full first sync, a second sync performs no additional `fetch_raw` calls (FR-026: known ids not fetched). |
| `test_new_message_imported_and_counted_only_once` | First sync imports all but one content-distinct importable fixture; adding that remaining fixture yields `n_found==1, n_imported==1, n_already==0` and stored emails increase by exactly 1. |
| `test_same_email_file_then_mailbox_already_processed` | Same email first imported from file, then seen from mailbox: `n_found==1, n_already==1, n_imported==0`. |
| `test_interruption_after_n_keeps_them_and_resumes` | With unambiguous oldest-first order (strictly increasing dates, zero-padded ids), a `SourceUnavailable` on the 4th fetch leaves exactly `msg00,msg01,msg02` stored and `last_attempt_status='failed'`; a later healthy sync resumes (`n_found==9`, `n_imported+n_rejected+n_already==n_found`), total 12 stored with mailbox ids, and `last_attempt_status='ok'`/`last_success_at` set. |
| `test_auth_revoked_sets_state_and_pauses` | `AuthRevoked` (`invalid_grant`) results in persisted `mailbox_state.auth_state='revoked'` and `auto_sync='paused_auth'` (FR-029, US1-8). Scheduler-skip is NOT asserted here (see OPEN DECISION B). |
| `test_folder_not_found_reports_name_and_reads_nothing` | `FolderNotFound` yields `last_error == "carpeta Idealista no encontrada"` and `last_attempt_status='failed'`, zero `alert_emails`, and zero `list_ids`/`fetch_raw` calls. |
| `test_source_unavailable_records_error_and_schedule_continues` | `SourceUnavailable` records `last_error` and `last_attempt_status='failed'` but leaves `auth_state='valid'` and `auto_sync='on'`. |
| `test_second_concurrent_sync_refused` | While one sync blocks, a second does not raise and returns the exact refusal string `"sync already running"` (as a value anywhere in its returned value); the first completes with `n_found==12, n_imported==11, n_rejected==1`, and the source saw only the first sync's list/fetch calls (no extra). |
| `test_out_of_date_after_failure_or_stale_success` | `alerts_sync.out_of_date(state, now)`: true after failed attempt or when last success > 30 min ago; false when fresh (10 min) or exactly 30 min; true at 30 min + 1 s; true for a failed attempt even with a fresh `last_success_at` (assumption stated below). |
| `test_thousand_message_backlog_under_ten_minutes` (`@pytest.mark.slow`) | 1,000 content-distinct messages (unique `Message-ID` per message) sync with `n_found==1000`, `n_imported+n_already+n_rejected==1000`, `n_failed==0`, in < 600 s (SC-010). |

## Failure reason observed (right reason)
Ran (isolated env `CASA_DB/NEEDS/APPDATA` under `$env:TEMP\casa-agent-T053`, needs copied from `config/needs.example.yaml`):
`python -m pytest tests/test_sync.py -q` → **12 failed in 34.23s**. Every test fails with
`ImportError: cannot import name 'alerts_sync' from 'app'` (lazy import of `app.alerts_sync`). This is the expected/accepted failure because `app/mailbox/*` and `app/alerts_sync.py` do not exist yet (implementation out of scope). Lazy imports keep failures per-test (no single collection error).

## OPEN DECISIONS (for user/coordinator before T058/T059)

- **(A) Raise vs return on named errors — NOT pinned.** The docs say "stop; error recorded" (R6/contract) but do not state whether `sync()` raises or returns a failed summary. Tests call sync through `_invoke_sync`, which accepts either a returned summary or ONLY `AuthRevoked`/`FolderNotFound`/`SourceUnavailable` escaping, and assert strictly on persisted state (`mailbox_state`, `import_runs`, `alert_emails`) and source call counts. No other exception is swallowed. **Decide the contract before T058 is dispatched.**
- **(B) Scheduler skip — NOT covered here.** T053 mentions "scheduler skips" but no scheduler predicate is named in the docs (behavior belongs to T059 / `app/main.py` lifespan: run only when `auth_state='valid'` and `auto_sync='on'`). The invented `sync(kind='sync_scheduled')` no-op test was removed. Persisted `auth_state='revoked'`/`auto_sync='paused_auth'` is asserted; the scheduler-skip behavior **must be tested with T059**. **Decide/confirm coverage with the user.**

## Proposed / undocumented interfaces and assumptions (reviewer notes)

- **(C) Concurrency refusal shape (proposed).** Per T058/R6 the second call returns `"sync already running"`; tests assert it does not raise and that the exact string appears as a returned value (or nested within the returned structure), and that the second call listed/fetched nothing extra. The full summary/return shape for a refused sync is otherwise undocumented.
- **Sync API shape (proposed):** `app.alerts_sync.sync(conn, source, kind=...)` returning a run summary dict (at least `run_id`, `n_found`, `n_imported`, `n_already`, `n_rejected`; `n_failed` checked when present) and `app.alerts_sync.out_of_date(state, now) -> bool`, mirroring `alerts.import_paths`/R6. If names/signatures differ, tests must be adapted by the implementer.
- **Mailbox state seeding:** tests insert a `mailbox_state` row directly (including `backfill_from=None` for the first-sync case).
- **(D) `out_of_date` state shape assumption:** state is dict-like with `last_attempt_status` and `last_success_at` as a naive/local ISO timestamp string (consistent with `alerts._now()`/`datetime.now()` comparisons). Rule interpreted as: "older than 30 minutes" (exactly 30 min = not out of date; 30 min + 1 s = out of date); a failed last attempt means out of date even if `last_success_at` is fresh.
- **Interruption/resume:** `process_message` stores every processed email (including rejected) with its `mailbox_id`; the interruption test relies on this to count exact stored ids.

## Gates run
- `python -m compileall -q app tests` — exit 0
- `python tests/fixtures/anonymise_eml.py --check tests/fixtures/emails` — exit 0
- `git diff main...HEAD -- requirements.txt` — empty
- `git diff --name-only main...HEAD` — `specs/001-alert-email-import/handoffs/T053-tests.md`, `tests/test_sync.py` (this commit)
