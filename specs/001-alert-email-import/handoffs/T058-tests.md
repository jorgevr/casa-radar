# T058 tests handoff — fix two wrong sync tests (user-approved)

## Status
Two approved edits applied to `tests/test_sync.py` only. `python -m compileall -q app tests` passed. `python -m pytest -q tests/test_sync.py -m "not slow"` still fails (1 failed, 10 passed, 1 deselected): `test_first_sync_uses_30_day_window_sets_backfill_and_skips_older` now stores `{'old','recent'}` instead of only `{'recent'}`. No other tests were changed or weakened.

## Exact diff summary
File: `tests/test_sync.py`

```diff
diff --git a/tests/test_sync.py b/tests/test_sync.py
--- a/tests/test_sync.py
+++ b/tests/test_sync.py
@@ -216,7 +216,7 @@ def test_first_sync_uses_30_day_window_sets_backfill_and_skips_older(conn, no_ne
     assert exc is None
     assert src.list_calls, "sync must list the mailbox"
     assert src.list_calls[0][1] == today - timedelta(days=30)
-    assert "old" not in src.fetch_calls
+    # The `after` filter is applied by the source (FR-027); sync only has to pass `today - 30 days`.
     stored = {r["mailbox_id"] for r in conn.execute("SELECT mailbox_id FROM alert_emails")}
     assert stored == {"recent"}
     st = _state(conn)
@@ -383,7 +383,6 @@ def test_second_concurrent_sync_refused(conn, no_network):
 
     class BlockingSource(FakeMailSource):
         def list_ids(self, folder_id, after):
-            self.list_calls.append((folder_id, after))
             started.set()
             release.wait(timeout=5)
             return super().list_ids(folder_id, after)
```

## Why each edit is safe

1. **`test_second_concurrent_sync_refused` / `BlockingSource.list_ids`**: removed the duplicate `self.list_calls.append((folder_id, after))` inside the blocking override. `FakeMailSource.list_ids` (super) already records `list_calls`, so the override caused one real call to be logged twice. Removing the duplicate aligns the instrumentation with actual behavior without changing sync behavior or test intent.
2. **`test_first_sync_uses_30_day_window_sets_backfill_and_skips_older`**: removed only `assert "old" not in src.fetch_calls` and replaced it with a comment. The fake is configured with `respect_after=False` and the "old" message's date is only known from the fake's metadata, so sync cannot know its date before fetching it; the `after` filter is the source's responsibility (FR-027). The removed assertion was therefore impossible for a correct implementation given this fake setup.

## What each edited test still asserts

1. **`test_second_concurrent_sync_refused`**: still asserts the first sync result (`n_found == 12`, `n_imported == IMPORTED`, `n_rejected == REJECTED`, no exception), the second call is refused with `"sync already running"` and does not raise, and no extra list/fetch work happens (`len(src.list_calls) == 1`, `len(src.fetch_calls) == 12`). Only the duplicate instrumentation append was removed.
2. **`test_first_sync_uses_30_day_window_sets_backfill_and_skips_older`**: still asserts no exception, sync lists the mailbox, the first list call passes `today - timedelta(days=30)` as `after`, only `"recent"` is stored in `alert_emails`, and `mailbox_state.backfill_from` is set to `today - 30 days`.

## Remaining failure (not edited further)
- `tests/test_sync.py::test_first_sync_uses_30_day_window_sets_backfill_and_skips_older` fails with `AssertionError: assert {'old', 'recent'} == {'recent'}` because the fake lists all messages (`respect_after=False`) and sync fetches/processes what the source returns; sync cannot exclude "old" pre-fetch. With the impossible "not fetched" assertion removed, the remaining `stored == {"recent"}` assertion is incompatible with this fake unless the fake enforces `after` or the test expectation is adjusted. Per instructions I did not weaken or edit other tests/assertions; this needs reviewer/coordinator decision.

## Isolation used for verification
- `CASA_DB=$env:TEMP\casa-agent-T058-tests\casa.db`
- `CASA_NEEDS=$env:TEMP\casa-agent-T058-tests\needs.yaml` (copied from `config/needs.example.yaml`)
- `CASA_APPDATA=$env:TEMP\casa-agent-T058-tests\appdata`

## Gates run
- `python -m pytest -q tests/test_sync.py -m "not slow"` (isolated): 10 passed, 1 failed, 1 deselected
- `python -m compileall -q app tests`: passed
