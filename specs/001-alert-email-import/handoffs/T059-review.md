# T059 review

**Verdict: [PASS]** (no blocking findings; 6 non-blocking items, two worth fixing before T060+ build on this)

Scope: `git diff jorgevr/Implementation...HEAD` (4 files: `app/main.py`, `tests/test_api_mailbox.py`, two handoffs).
Run in an isolated env (CASA_DB/CASA_NEEDS/CASA_APPDATA in `%TEMP%`): `compileall` ok; `pytest tests/test_api_mailbox.py` 25 passed;
`requirements.txt` diff empty; no data/config/secret/.eml files in the diff. (The full `-m "not slow"` run exceeded my 120 s tool
timeout and was left in the background; the dev handoff reports 568 passed. I did not rely on it.)

## Test-edit audit (ec2a260 → HEAD)

`git diff ec2a260 HEAD -- tests/test_api_mailbox.py` shows exactly the three approved edits and nothing else:
1. d17a0c3: new `no_external_network` fixture + its own test; six scheduler tests switched from `no_network` to it.
2. d17a0c3: `recent_success = (datetime.now() - timedelta(minutes=1))…` seed and the matching `assert data["last_success_at"] == recent_success`.
3. fa290c8: `if len(sleeps) >= 3` → `>= 4` (runs test) and `if ticks["n"] >= 3` → `>= 4` (source-error test). Expected counts
   (`len(calls) == 3`) are unchanged; the cancel point moved one sleep later, which is the correct off-by-one (3 syncs need 3 completed ticks, cancel on the 4th sleep).
No assertion was removed or loosened. [OK]

## (1) Contract: endpoints, status codes, bodies

- `GET /api/mailbox` — `app/main.py:459-480`. Returns exactly the 16 contract keys (provider … `app_folder`); `reauthorise_steps` is
  `list(REAUTHORISE_STEPS) if st.get("auth_state") == "revoked" else None` (l.478), `progress` is `{done,total}` only while running, else null. [OK]
  Not configured: `st = {"auth_state": "not_configured", "auto_sync": "on"}` — all other fields null, honest. [OK]
- `POST /api/mailbox/authorise` — l.505-508 `status_code=202`, `{"waiting": True}`; flow in a daemon thread. [OK]
- `PUT /api/mailbox/folder` — l.510-526: 400 on bad body, `404 {"error": f"folder {name} not found"}` matches contract text exactly, 409/502 for
  AuthRevoked/SourceUnavailable (beyond contract, sensible). [OK]
- `POST /api/mailbox/sync` — l.527-568: `202 {"run_id": n}`, `409 {"error": "sync already running"}` (l.534-535) matches contract. 409 for not-configured/revoked is an extension. [OK]
- `POST /api/mailbox/disconnect` — l.570-576: deletes token, clears cache, `auth_state="not_configured"`. [OK]
- Secrets: no endpoint reads a refresh/access token or client secret. Logs use `type(exc).__name__` only
  (`log.warning("mailbox authorisation failed: %s", type(exc).__name__)`, `log.warning("mailbox sync failed: %s", …)`, scheduler likewise);
  `last_error` stores `f"autorización no completada ({type(exc).__name__})"`. `app_folder` is a path, required by the contract. Test
  `test_authorise_failure_reflected_in_state_no_secrets` plants `FAKE_SECRET` in the exception message. [OK]

## (2) Lifespan scheduler

- Interval: `mailbox_interval_minutes(state)` falls back to `SYNC_INTERVAL_DEFAULT_MINUTES = 15` (named constant, l.41); `mailbox_state` has no
  `interval_minutes` column (`app/db.py:58-63`), so in production it is always the constant (dev handoff says so). [OK, note]
- Skip rule: `return state.get("auth_state") == "valid" and state.get("auto_sync") == "on"`, with `sync_running or not state` → False. [OK]
- One guard for manual and scheduled: `sync_guard = threading.Lock()`; `run_guarded` does `if not sync_guard.acquire(blocking=False): return None`
  (l.129); manual does the same (l.534); scheduler checks `is_running=sync_guard.locked`. Race between the check and acquire only skips a tick. [OK]
- Off the event loop: `await asyncio.to_thread(run_guarded, "sync_scheduled")`. Own connection `wconn = db.connect(db_path)`. [OK]
- Sync errors do not stop the loop: `except Exception as exc: log.warning(...)` inside the `while True`. [OK]
- Cancel + await on shutdown: `task.cancel()` then `await task` swallowing `CancelledError`, then `_close_mail_client()`. [OK]

**N1 (non-blocking, recommended fix):** `get_state()` is called *outside* the try: `wait = interval_seconds if interval_seconds is not None else
mailbox_interval_minutes(get_state()) * 60` (l.100) and `if not mailbox_should_sync(get_state(), …)` (l.102). `_scheduler_state` opens a fresh
`db.connect` (which runs `executescript(SCHEMA)` + `migrate` + commit, `app/db.py:80-90`) on the event-loop thread. A transient
`sqlite3.OperationalError` ("database is locked" while the sync worker commits) would escape the task and end the scheduler for the rest of the
process, silently (nobody awaits the task until shutdown). Impact: auto-sync stops until restart; visible only as `out_of_date`. Fix: put the state
read in the same `try/except Exception` (fall back to the default interval) and do it via `asyncio.to_thread`.

**N2 (non-blocking):** shutdown while a sync is in flight. `task.cancel()` cannot stop the `to_thread` worker; `_close_mail_client()`
(l.159) then closes the shared httpx client under it. alerts_sync's `except BaseException` finalises the run as failed, so no corrupt state, but the
error is spurious. Manual-sync workers are `daemon=True` threads, so a process exit mid-run leaves `import_runs.status='running'` and
`mailbox_state.running_run_id` set (see N3). Acceptable for single-user v1; document.

No thread leaked on the normal path: the scheduler task is awaited; manual/authorise threads are daemon and end on their own.

## (3) SQLite across threads

`db.connect` uses `check_same_thread=False` (`app/db.py:85`), and the app already shares the one `conn` across FastAPI's threadpool, so the request
connection is not new exposure. T059 adds no cross-thread use of `conn`: the sync worker (l.541-545), scheduled run (l.131-135), authorise worker (l.483)
and scheduler state read (l.119-124) each open and close their own connection. Request handlers only use `conn` for `read_state()`, `ensure_state_row`
and `write_state` (folder/disconnect). Two writers on separate connections rely on SQLite's 5 s busy timeout; sync writes are short commits. [OK]

## (4) CSRF / DNS rebinding

Authorise, sync and disconnect take no body and no auth, and the app has no Origin/Host check or CORS config (`grep CORS|TrustedHost|Origin` in
`app/main.py`/`app/cli.py`: none). A page in the user's browser can fire `fetch(..., {mode:"no-cors", method:"POST"})` or a form POST at
`http://127.0.0.1:<port>/api/mailbox/...` (a simple request, no preflight, and these handlers do not parse a body).
- authorise: pops a Google consent page in the browser; the attacker cannot read the code (loopback redirect, PKCE + state in `oauth.authorize`). Annoyance, and repeated calls spawn
  one daemon thread + loopback listener + browser tab per call (no guard) until each times out. **Low.**
- sync: starts a read-only mailbox import the user already allows every 15 min. **Low.**
- disconnect: deletes the stored token, forcing re-authorisation. **Low-medium** (availability, no data loss).
- DNS rebinding additionally lets a hostile origin *read* `GET /api/mailbox` (no secrets, but account e-mail address and folder name) — and every other
  GET.
Same exposure as existing routes: `POST /api/listings`, `PUT /api/needs`, `POST /api/alerts/import`, `POST /api/alerts/reprocess`,
`PUT /api/categories`, `POST /api/listings/{id}/merge` (l.172-429) all accept the same unauthenticated cross-origin writes, and those can read/alter the
household data. So T059 adds no new class of exposure. **Non-blocking (N3a)**; recommend a single follow-up task (Host-header allow-list `127.0.0.1`/`localhost` +
reject non-JSON POST / foreign Origin) for the whole app rather than for T059. Optional small hardening in T059: refuse a second authorise while one is in progress.

## (5) "Sync now" run_id fallback

Code: `last = conn.execute("SELECT COALESCE(MAX(run_id), 0) FROM import_runs")…` (l.552) … `run_id = last + 1  # the worker has not opened its run yet` (l.567),
used when no int was found within `RUN_ID_WAIT_SECONDS = 0.5`. The returned id can be wrong or non-existent when:
- **a)** the worker has not called `start_run` within 0.5 s (cold httpx import, slow DB open) *and* the next AUTOINCREMENT value equals MAX+1 → correct. It is wrong if
  rows were deleted (AUTOINCREMENT's `sqlite_sequence` can exceed MAX(run_id)), or if another run (`/api/alerts/import`, `/reprocess`, which are not under `sync_guard`)
  inserts between the read at l.552 and the worker's `start_run` → the id returned belongs to that other run;
- **b)** the sync never creates a run (`get_mail_source()` raises before `alerts_sync.sync`, e.g. missing httpx/client secret → worker logs and exits;
  or `sync` returns the `already_running` summary which has no `run_id`) → `last + 1` does not exist;
- **c)** `running_run_id` is stale from a crashed process (`mailbox_state.running_run_id` never cleared, see N2): the loop's first iteration at l.563 returns that old id immediately,
  before the new worker opens its run.
UI harm: the UI uses `run_id` to poll `GET /api/runs/{id}`; (a)/(b) give a 404 or another run's summary for a moment; (c) shows an old finished/"running" run. Not corrupting;
the UI should also poll `GET /api/mailbox` (`running`, `progress`) which is authoritative. **Non-blocking (N3)**; honest alternative: wait for the worker's
real id (blocking up to a few seconds) or return `run_id: null` — but the contract demands an int, and the dev flagged this inference explicitly. Recommend (c) fix: ignore
`running_run_id` unless > `last`.

## (6) Wiring

`default_app()` → `create_app(enable_mailbox_scheduler=True)` (l.654-655); `create_app(db_path, needs_path, *, enable_mailbox_scheduler=False)` leaves the
lifespan task off. `app/cli.py serve` runs `uvicorn.run("app.main:default_app", factory=True, …)` (per dev handoff; `app/cli.py` is untouched), so the real server starts the
scheduler. Existing tests call `create_app(...)` → unchanged. TestClient used without a `with` does not run lifespan, as before. [OK]
Minor: `default_app` passes no `db_path`, so `_scheduler_state(None)` uses `db.DB_PATH` — same resolution as the app's own connection. [OK]

## (7) Constitution

- No imputed values: not-configured and revoked report `null` plus honest `auth_state`; `out_of_date` on an unparsable timestamp → True (stated, not guessed). [OK]
- No threshold/interval literals in logic: `SYNC_INTERVAL_DEFAULT_MINUTES`, `RUN_ID_WAIT_SECONDS` named; the 0.02 s poll step in `done.wait(0.02)` (l.560) is an unnamed literal (trivial,
  non-scoring). 30-minute staleness stays in `alerts_sync.STALE_AFTER`. [OK, nit]
- No new dependency (httpx already used); no network in tests; among hot files only `app/main.py` changed (`db.py`, `cli.py`, `index.html`, `conftest.py` untouched). [OK]

## (8) Test quality

Nothing is vacuous in the scheduler/unit tests (interval, default, skip matrix, running skip, error survival; all assert call counts/sleep values).
`test_no_external_network_fixture_blocks_non_loopback_and_allows_loopback` really proves the fixture: it raises `AssertionError("network access in test")` for
`203.0.113.1` via both `create_connection` and `socket.connect`, and connects to a bound loopback listener. Caveat: it patches `connect`, not `connect_ex`/`getaddrinfo`, so DNS
lookups are not refused (the real `no_network` fixture is stricter, but TestClient/asyncio on Windows need loopback). **Non-blocking (T1).**
Weak points (all non-blocking):
- **T2** `test_authorise_failure_reflected_in_state_no_secrets` ends with `assert data["auth_state"] in ("revoked", "valid", "not_configured")` — satisfied by every possible state — and
  `if data.get("last_error"):` makes the secret check conditional. Only `assert_no_secrets(st)` is a real check. It would also pass if authorise did nothing. 
- **T3** `test_authorise_returns_202_waiting` never asserts `fake_authorize` ran (`started.wait(timeout=2)` result ignored) and monkeypatches two guessed names with `raising=False`.
- **T4** `test_sync_rejected_when_not_configured`/`_revoked`: `status_code in (400, 409)`, and `"configur" in … or "not" in …` (an "and/or"-optional assertion). The implementation returns 409 with
  fixed text, so these can be tightened to equality.
- **T5** `test_scheduler_clean_shutdown_no_real_sync` only asserts `real_calls["n"] == 0`; it does not check the task was created, cancelled and awaited, and would pass with the lifespan
  scheduler deleted. The 15-minute lifespan wiring (cancel+await, thread off the loop, guard shared with manual sync) therefore has no direct test; N1/N2 are untested.
- **T6** No test for the run_id fallback (l.552-567) or for `default_app()` enabling the scheduler.
They fail without the implementation (each endpoint/seam is missing on the base; `mailbox_scheduler`, `mailbox_should_sync`, `enable_mailbox_scheduler` are import/attribute errors).

## Summary

Blocking: none. Non-blocking, in priority order: N1 (scheduler can die on a state-read error), N3(c)/(a)/(b) (run_id fallback precision), T2/T4/T5 (tighten tests —
these are edits that need the user's approval since tests are first), N3a (app-wide CSRF/Host hardening as its own task), N2 (shutdown during a running sync), T1, T3, T6.
