# T058 follow-up review

**Verdict: [PASS]**

Scope: `git diff jorgevr/Implementation...HEAD`. Files changed: `app/alerts_sync.py` (+6/-4), `tests/test_sync.py` (+34/-0),
`handoffs/T058-followup.md` (+24). `app/db.py`, `app/alerts.py` and every other file are untouched.
Isolation: CASA_DB/CASA_NEEDS/CASA_APPDATA pointed to a temp folder. `pytest tests/test_sync.py`: 13 passed.

## Checks

1. **BaseException branch finalises and re-raises.** `app/alerts_sync.py:76-80`:
   `except BaseException as exc:` then `write_state(conn, last_attempt_status="failed", last_error=type(exc).__name__, ..., running_run_id=None)`,
   `alerts.finish_run(conn, run_id, "failed", type(exc).__name__)`, bare `raise`. A bare `raise` keeps the original
   exception object and traceback intact. OK.
2. **Handler order unchanged.** `AuthRevoked` (:68), `FolderNotFound` (:71) and `SourceUnavailable` (:74) come first
   with their original bodies; only the last clause changed from `Exception` to `BaseException`. Python picks the first
   matching clause, so the mapping is unchanged. Are these classes `Exception` subclasses and not `BaseException`
   ones? Not re-verified beyond the passing existing auth/folder/unavailable tests. OK.
3. **Lock released on every path.** `sync()` at :79-84 holds `try: return _run(...) finally: _LOCK.release()`. This
   covers a re-raise from `_run` and a failure inside the handler. OK.
4. **New test is meaningful.** `tests/test_sync.py` `test_keyboard_interrupt_finalises_run_state_and_releases_lock`:
   `raise KeyboardInterrupt  # simulated Ctrl+C, no real signal` in `fetch_raw` for `msg03`;
   `with pytest.raises(KeyboardInterrupt):` (propagation);
   `assert run["status"] == "failed"` and `assert run["finished_at"] is not None` (failed run);
   `assert st["running_run_id"] is None`, `st["last_attempt_status"] == "failed"`, `st["last_error"] == "KeyboardInterrupt"` (state cleared);
   `assert stored == {"msg00", "msg01", "msg02"}` (messages kept);
   a follow-up `sync` returning `result["status"] == "ok"` and `result["n_found"] == 9` (lock free, not `already_running`, resumes).
   Fails without the change: the old `except Exception` does not catch `KeyboardInterrupt`, so the run stays `running`
   and `running_run_id` stays set, failing the `running_run_id is None` / `status == "failed"` asserts. I reasoned this
   from the code rather than reverting it (read-only review). The test is offline and uses no real signal or data.
5. **No test weakened.** `--numstat` for `tests/test_sync.py` is `34 0`: additions only, no deleted or edited lines.
6. **No secrets/PII.** Stored error fields are `type(exc).__name__` only (:77-79), never message text, paths or tokens.
7. **Docstrings.** Module docstring (:3-6), `sync` docstring (:78) and `_window_start` docstring (:69) changed.
   *Minor note:* the `_window_start` edit ("never earlier than backfill" → "not clamped to backfill_from") goes slightly
   beyond the exception topic, but it is a stale-docstring fix and accurate (no clamp exists in :69-73). Allowed by the task. No code changes elsewhere.

## Residual risk: finalisation itself failing

If `write_state`/`finish_run` raise inside the handler (closed connection, `sqlite3.OperationalError: database is locked`,
disk full, or a second Ctrl+C), the new exception propagates instead of the original. Python sets the original as
`__context__` ("During handling of the above exception, another exception occurred"), so it stays visible in the traceback,
and the `finally` still releases the lock. Likelihood: low but not zero. A locked/busy DB is the realistic case. In that
case the run stays `running`, which is the same state as before this change, so there is no regression. Implicit chaining
is acceptable for a single-user local tool. Suppressing the secondary error or wrapping finalisation in try/except would
add complexity and risk hiding DB faults, and it is not needed. Optional hardening (not required, not requested): none.

## Out of scope, unchanged (informational)

Failures between `alerts.start_run` and the `try` (:34-38, the `write_state` calls) are not covered by the handler.
That is pre-existing and was not part of the request.
