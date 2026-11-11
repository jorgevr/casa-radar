# T058 review — [PASS]

Isolation: CASA_DB / CASA_NEEDS / CASA_APPDATA pointed at `%TEMP%\casa-agent-rev`. No network or mailbox access.
Checks run: `compileall` ok; `tests/test_sync.py` 12 passed; anonymise `--check` clean; the files changed vs
`jorgevr/Implementation` are only `app/alerts_sync.py`, the two handoffs and `tests/test_sync.py`; `requirements.txt` diff empty.
The full `-m "not slow"` suite did not finish within the review window (about 60 s for test_sync alone), so I did not read a full-suite result.

## Test edits (`git diff 428cdc2 HEAD -- tests/`)
Only `tests/test_sync.py` and the tests handoff changed, 3 lines in the test file. All three are the user-approved edits.
- Removed `self.list_calls.append((folder_id, after))` from `BlockingSource.list_ids`. The `len(list_calls) == 1` assertion is kept.
- `respect_after=False` -> `respect_after=True`; the comment was updated; `assert "old" not in src.fetch_calls` is kept.
- No behavioural assertion was weakened.

## Checklist
- [OK] Lock is non-blocking and always released. `app/alerts_sync.py:76` `if not _LOCK.acquire(blocking=False):`, then `:78-81` `try: return _run(...) finally: _LOCK.release()`.
- [OK] A refused call has no side effects. It returns at `:77` `return _summary("already_running", message=REFUSED)` before any DB read or write. It returns no exception and `error` is None.
- [OK] One transaction per message. `:123` `alerts.process_message(...)` runs in `with conn:` (`alerts.py:188`), so a failure rolls back that message only. Earlier messages stay committed (SC-010).
- [OK] Rules are loaded once per run (`:103`) and passed to every message (`:123` `rules=rules`). ValueError -> `rules, run_error = [], f"ValueError: {exc}"` (`:105`), recorded with status ok (`:147`).
- [OK] Known ids are skipped before fetch. `:114` `if mid not in known and mid not in seen:` runs before `:120` `source.fetch_raw`. The window is `last_success - 2d` or `today - 30d` (`:66-71`). Backfill is set at `:94-95`.
- [OK] AuthRevoked sets the state at `:127` `write_state(conn, auth_state="revoked", auto_sync="paused_auth")`.
- [OK] FolderNotFound: `resolve_folder` raises before `list_ids` is called, so nothing is read.
- [OK] SourceUnavailable records an error and does not touch `auto_sync` (`:131-132`).
- [OK] Label re-resolution: `:108-109` `notice = "folder identity changed"`, and `:110` stores the new id.
- [OK] `out_of_date` (`:48-57`) is true after a failure or when the last success is older than `STALE_AFTER`.
  The constants `FIRST_SYNC_DAYS`, `OVERLAP_DAYS` and `STALE_AFTER` are named, at module level (`:15-17`). The repo has no config home for them; `gmail.py` also keeps `MIN_INTERVAL_SECONDS` at module level.
- [OK] No secrets, tokens, raw email content or PII are stored. `last_error` holds fixed Spanish texts (`:126,130,132`), and the run error holds a short code. The unexpected-exception path stores only `type(exc).__name__` (`:134-136`). The one exception is the user-chosen label name in `:130`, which is configuration, not email content.
- [OK] No imputed values: no state row raises `RuntimeError` (`:87`). No new dependency and no network. Hot files `app/db.py` and `app/alerts.py` are untouched.
- [OK] WrongFolder is skipped at `:121-122` `except WrongFolder: continue`. The message is not stored, so it is retried next sync.
- [OK] Unexpected exceptions mark state and run as failed, clear `running_run_id`, then re-raise (`:133-137`), as the handoff states.
- [OK] Source order is kept, per the user's decision.

## Minor notes (none blocking)
1. `:105` `run_error` is lost if a source error follows. A rules ValueError is stored only on the ok path (`:147`). On the error path `finish_run(conn, run_id, "failed", error)` (`:143`) overwrites it. This is acceptable because the task says the ValueError is recorded "with status ok".
2. `:122` `continue` on WrongFolder skips `write_state(conn, progress_done=done)` for that message, so progress can end below `progress_total`. It is cosmetic.
3. `:133` `except Exception` does not cover `BaseException` (KeyboardInterrupt, SystemExit). The lock is still released by the `finally`, but `running_run_id` and the run stay `running`. There is no recovery path here; T059 or startup could clear stale running state.
4. `:67` The docstring says "never earlier than backfill", but the code does not clamp to `backfill_from`. This is harmless, since last success - 2d is never earlier than the 30-day backfill in practice. Fix the comment or the code.
5. `:77` The refusal summary adds `message` and `:150` adds `run_id` and `notice`. These keys are beyond decisions.md and are tests-driven, as the dev handoff says.
