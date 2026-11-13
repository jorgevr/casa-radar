# T059 follow-up — scheduler survives state-read errors (N1)

## What changed
- `app/main.py`
  - New `_read_scheduler_state(get_state)`: calls `get_state()` (awaits it if it returns an awaitable), catches `Exception`
    only (never `CancelledError`), logs the exception type name only, returns `(state, ok)`.
  - `mailbox_scheduler` now reads state through it for BOTH the interval and the sync decision. Unreadable state ->
    `mailbox_interval_minutes(None)` = `SYNC_INTERVAL_DEFAULT_MINUTES` for the sleep, and the tick is skipped
    (no sync); the loop keeps ticking. Signature unchanged; plain-callable `get_state` still works.
  - Lifespan wiring passes an async `scheduler_state()` that runs `_scheduler_state(db_path)` via `asyncio.to_thread`,
    so the sqlite read is off the event-loop thread.
- `tests/test_api_mailbox.py` (appended only, no existing test touched):
  - `test_scheduler_survives_state_read_errors_and_recovers` — OperationalError on reads 1-3; sleeps `[default, default, 420, 420]`, 2 syncs.
  - `test_scheduler_state_read_error_in_decision_only_skips_that_tick` — decision read fails once; that tick skipped, next syncs.
  - `test_scheduler_cancellation_during_state_read_still_propagates` — CancelledError not swallowed.
  - `test_scheduler_accepts_async_get_state` — awaitable get_state supported (production wrapper).

## Red phase
Before the change 3 of the 4 failed (OperationalError / un-awaited coroutine escaped); the cancellation test already passed (guards regression).

## Gates
- compileall: pass
- tests/test_api_mailbox.py: 29 passed
- full `-m "not slow"`: 572 passed, 1 skipped, 2 deselected
- anonymise_eml --check: pass (no output)
- `git diff --name-only main...HEAD`: nothing under data/, no needs.yaml / zone_aliases.yaml / client_secret* / token*, no .eml
- requirements.txt diff: empty

## Reviewer check
Decision-read failure skips the tick without consulting `is_running`; async get_state support is a small seam extension (additive).
