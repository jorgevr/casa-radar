# T058 follow-up — BaseException finalisation

## Changed
- `app/alerts_sync.py`: the unexpected-error branch is now `except BaseException` (after the three named source
  errors, which are unchanged). It marks the run `failed` (error = exception class name), sets
  `last_attempt_status=failed`, `last_error`, `last_error_at`, clears `running_run_id`, and re-raises. The
  `finally` in `sync()` already releases the lock.
- Docstrings: module docstring now states the BaseException behaviour; `_window_start` no longer claims a
  clamp to backfill (review note 4); `sync()` docstring says other exceptions re-raise.
- `tests/test_sync.py`: new `test_keyboard_interrupt_finalises_run_state_and_releases_lock` (source raises
  KeyboardInterrupt on the 4th fetch; asserts it propagates, run failed with finished_at, running_run_id
  null, last_error `KeyboardInterrupt`, msg00-msg02 stay stored, next sync runs ok with n_found 9).
  Confirmed red first (run stayed `running`), then green. No existing test touched.

## Decisions not covered by docs
- Proposed doc note (research R6 / decisions.md): "any exception, including KeyboardInterrupt/SystemExit,
  finalises the run as failed and releases the lock before propagating."
- A failure inside the finalisation itself (e.g. DB closed) would replace the original exception; not handled.

## Gates
See worker_done message / below.

Results: compileall ok; `pytest -m "not slow"` 533 passed, 1 skipped, 2 deselected; anonymise --check exit 0;
no forbidden paths in `git diff --name-only main...HEAD`; requirements.txt diff empty.
