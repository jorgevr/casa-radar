# T058 tests handoff — fix two wrong sync tests (user-approved)

## Status
User-approved edits applied to `tests/test_sync.py` only. After the additional approved follow-up edit to `test_first_sync_uses_30_day_window_sets_backfill_and_skips_older` (use `respect_after=True` and restore `assert "old" not in src.fetch_calls`), isolated verification passes: `python -m pytest -q tests/test_sync.py -m "not slow"` (11 passed, 1 deselected) and `python -m compileall -q app tests` (ok). No other tests or `app/` were changed.

## Edits made (cumulative, all user-approved)
File: `tests/test_sync.py`

1. **`test_second_concurrent_sync_refused` / `BlockingSource.list_ids`**: removed duplicate `self.list_calls.append((folder_id, after))` (super already records calls); kept `started.set()`, `release.wait(timeout=5)`, and `return super().list_ids(folder_id, after)`.
2. **`test_first_sync_uses_30_day_window_sets_backfill_and_skips_older`**: replaced the "fake ignores `after`" setup/comment with `respect_after=True` and a short comment that the fake filters by `after` as Gmail does (FR-027), and restored `assert "old" not in src.fetch_calls`.

## Why each edit is safe
1. The duplicate append caused one real `list_ids` call to be logged twice; removing it aligns instrumentation with actual behavior and test intent.
2. With `respect_after=True`, the fake applies the `after` filter like Gmail (FR-027), so asserting "old" is not fetched/stored is consistent and verifiable while sync still only needs to pass `today - 30 days`.

## What each edited test still asserts
1. **`test_second_concurrent_sync_refused`**: first sync returns `n_found == 12`, `n_imported == IMPORTED`, `n_rejected == REJECTED` with no exception; second call returns refusal `"sync already running"` without raising; no extra work (`len(src.list_calls) == 1`, `len(src.fetch_calls) == 12`).
2. **`test_first_sync_uses_30_day_window_sets_backfill_and_skips_older`**: no exception; mailbox listed; first list call passes `after == today - timedelta(days=30)`; `"old"` not in `fetch_calls`; only `"recent"` stored in `alert_emails`; `mailbox_state.backfill_from == (today - 30 days)`.

## Isolation used for verification
- `CASA_DB=$env:TEMP\casa-agent-T058-tests\casa.db`
- `CASA_NEEDS=$env:TEMP\casa-agent-T058-tests\needs.yaml` (copied from `config/needs.example.yaml`)
- `CASA_APPDATA=$env:TEMP\casa-agent-T058-tests\appdata`

## Gates run
- `python -m pytest -q tests/test_sync.py -m "not slow"` (isolated): 11 passed, 1 deselected
- `python -m compileall -q app tests`: passed
