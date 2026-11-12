# T059 follow-up review (N1) — [PASS]

Diff reviewed: `git diff jorgevr/Implementation...HEAD` (app/main.py, tests/test_api_mailbox.py, handoffs/T059-followup.md only).

- Except clause: `app/main.py:104` `except Exception as exc:  # e.g. a transient 'database is locked'...` — Exception only; CancelledError (BaseException) propagates. Covered by `test_scheduler_cancellation_during_state_read_still_propagates` (passes).
- No busy loop / no sync on failed read: interval read failure -> `state=None`, `wait = mailbox_interval_minutes(state) * 60` then `await sleep(wait)`; decision read `if not ok or not mailbox_should_sync(...): continue` skips `run_sync` and goes back to a full sleep. Test 1 asserts sleeps `[default, default, 420, 420]` and `len(syncs) == 2`.
- Default not a literal: `mailbox_interval_minutes(None)` returns `SYNC_INTERVAL_DEFAULT_MINUTES` (main.py:87); test uses `m.SYNC_INTERVAL_DEFAULT_MINUTES * 60`.
- Logs: `log.warning("mailbox scheduler could not read state: %s", type(exc).__name__)` — type name only.
- Threading: lifespan `scheduler_state()` -> `await asyncio.to_thread(_scheduler_state, db_path)`; `_scheduler_state` (main.py:129-134) does `c = db.connect(db_path)` ... `finally: c.close()` per call, no shared connection.
- Seam: signature unchanged (`get_state, run_sync, is_running, sleep, interval_seconds`); plain callable still works, awaitable additionally supported via `inspect.isawaitable`. All 25 pre-existing tests in the file pass unchanged (29 passed total).
- Tests append-only: numstat `97 0 tests/test_api_mailbox.py` (zero deletions). Deterministic (fake_sleep, no real sleeps), assert exact sleep lists and sync counts. Red check: ran the new tests against the old app/main.py in a temp copy (outside repo): 3 of 4 fail (AttributeError at main.py:86 / OperationalError path), cancellation test already passes (regression guard, as the handoff states).
- Scope: only app/main.py touched in app/; no requirements.txt change, no new dependency, no secrets/data files.
- Env: CASA_DB/CASA_NEEDS/CASA_APPDATA set to %TEMP%\casa-agent; only tests/test_api_mailbox.py run.

Minor, non-blocking notes: (1) with `interval_seconds` set, the interval read is skipped (intended). (2) a failed decision read skips without consulting `is_running` (acceptable, noted in handoff). (3) Failed-read warnings are logged each tick (every 15 min at most) — fine.
