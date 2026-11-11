# T059 tests handoff (test author)

## Scope (tests only)

- Added `tests/test_api_mailbox.py` (only file created/edited besides this handoff). No changes under `app/`.
- Worktree merged with `git merge --no-edit jorgevr/Implementation` (fast-forward to fbe037c) before writing tests.
- Read: `AGENTS.md`, `specs/001-alert-email-import/decisions.md` (T059/T058), `specs/001-alert-email-import/contracts/api.md` (Mailbox), `specs/001-alert-email-import/contracts/mail-source.md`, `specs/001-alert-email-import/data-model.md` (`mailbox_state`), `specs/001-alert-email-import/research.md` R5/R6, `app/alerts_sync.py`, `app/mailbox/*.py`, `app/main.py`, `tests/conftest.py`, `tests/test_api_alerts.py`.

## What each test asserts

### 1. `GET /api/mailbox`
- `test_mailbox_get_not_configured_default`: with no `mailbox_state` row, returns 200 with the exact contract keys and a not-configured default (`auth_state='not_configured'`, account/label_name/progress `None`, `running/out_of_date False`, `reauthorise_steps null`).
- `test_mailbox_get_exact_keys_and_no_secrets`: seeded valid state -> 200 body contains all contract keys `{provider, account, label_name, auth_state, auto_sync, interval_minutes, backfill_from, last_success_at, last_attempt_status, last_error, last_error_at, out_of_date, running, progress, reauthorise_steps, app_folder}` with expected values; `interval_minutes==15`; no secret/token/client_secret/`refresh_token` string ever appears in the body (fake sentinels `FAKE-SECRET-refresh-token-1//0SHOULD-NOT-LEAK`, `FAKE-client-secret-GOCSPX-SHOULD-NOT-LEAK` asserted absent). `app_folder` equals the `CASA_APPDATA` folder.
- `test_mailbox_get_reauthorise_steps_revoked`: `auth_state='revoked'` -> `reauthorise_steps` is a non-empty `list[str]`.
- `test_mailbox_get_reauthorise_steps_null_when_not_revoked`: `auth_state` `valid` or not-configured -> `reauthorise_steps` is `null`.
- `test_mailbox_get_out_of_date_failed_attempt`: `last_attempt_status='failed'` -> `out_of_date True` (FR-028).
- `test_mailbox_get_out_of_date_stale_success`: `last_success_at` > 30 minutes ago -> `out_of_date True`.
- `test_mailbox_get_out_of_date_false_when_recent_success`: recent success, ok attempt -> `out_of_date False`.

### 2. `POST /api/mailbox/authorise`
- `test_authorise_returns_202_waiting`: seeds state, monkeypatches `app.mailbox.oauth.authorize`/`run_authorization` to block on an event; asserts `202 {"waiting": true}` and that the response returns before the (monkeypatched) authorize completes (non-blocking). Response must not block on the auth flow.
- `test_authorise_failure_reflected_in_state_no_secrets`: monkeypatched authorize raises `AuthRevoked` carrying a fake token string in its message; after completion `GET /api/mailbox` body contains no secret strings and the failure is reflected via state (state/error surfaced, never leaked).

### 3. `PUT /api/mailbox/folder`
- `test_folder_resolves_and_stores`: faked source `resolve_folder("Idealista") -> "LBL_NEW"` (hooked via `app.main.get_mail_source` and/or `app.mailbox.gmail.GmailSource`); request `{ "label_name": "Idealista" }` succeeds and `GET /api/mailbox` shows `label_name` stored.
- `test_folder_not_found_404`: faked source raises `FolderNotFound` -> `404 {"error": "folder Nope not found"}`.
- `test_folder_invalid_body_400`: bodies `{}`, `{"name":"x"}`, wrong type, empty string -> `400`.

### 4. `POST /api/mailbox/sync`
- `test_sync_returns_202_run_id_and_runs_in_worker`: monkeypatches `app.alerts_sync.sync` (and `app.main.sync_mailbox`/`run_sync` hooks) to record thread name and set an event; asserts `202 {"run_id": <int>}` and sync runs in a worker thread (not main thread).
- `test_sync_409_while_running`: slow faked sync holds a lock/event; second POST while running -> `409 {"error": "sync already running"}`.
- `test_sync_rejected_when_not_configured`: no `mailbox_state` row -> clear 4xx rejection (chosen 400/409) with an `error` indicating not configured.
- `test_sync_rejected_when_revoked`: `auth_state='revoked', auto_sync='paused_auth'` -> clear 4xx rejection (chosen 400/409) with an error.

### 5. `POST /api/mailbox/disconnect`
- `test_disconnect_deletes_token_and_sets_state`: monkeypatches `app.mailbox.credentials.delete_token` (and `app.main.delete_token`) to record call; asserts 200, delete called, `auth_state='not_configured'` after, and `auto_sync` consistent with data-model transitions (not `paused_auth`; accepts `on`/`off`).

### 6. Scheduler (decisions.md T059; seams chosen by tests)
- `test_scheduler_seam_constants_and_tick_decision`: `app.main.SYNC_INTERVAL_DEFAULT_MINUTES == 15`; `app.main.mailbox_should_sync(state, *, now=None, sync_running=False)` returns True only for `auth_state='valid' and auto_sync='on'` and not running; False when running or when state is revoked/not_configured/`paused_auth`/`off`.
- `test_scheduler_runs_at_interval_from_state`: drives `mailbox_scheduler` with injected fake `sleep` (records seconds, raises `CancelledError` after 3 ticks) and a valid state with `interval_minutes=7`; asserts every sleep is `7*60` seconds (uses `interval_minutes` from state, never a literal 15) and `run_sync` called each tick.
- `test_scheduler_uses_default_interval_when_missing`: no `interval_minutes` in state -> sleeps `15*60`.
- `test_scheduler_skips_when_not_valid_or_not_on`: for each of revoked+paused_auth, not_configured, valid+paused_auth, valid+off, `run_sync` is never called.
- `test_scheduler_skips_tick_while_running`: `is_running() -> True` => no `run_sync` calls across ticks.
- `test_scheduler_source_error_does_not_stop_schedule`: `run_sync` raises on first call and returns error on later calls; scheduler must not propagate and must keep calling across ticks (3 calls observed) so a source error does not stop the schedule.
- `test_scheduler_clean_shutdown_no_real_sync`: `create_app(..., enable_mailbox_scheduler=True)` context starts/stops cleanly with no real `alerts_sync.sync` call (not configured). (Seam param chosen; see below.)

All tests request the `no_network` fixture (offline). Only fakes/monkeypatches used; never real tokens/Google/browser/mailbox.

## Chosen scheduler seams (exact names/signatures) — developer implements to these

To satisfy "tests first" without a named seam in `tasks.md`, I chose the smallest seams in `app.main` (keeping `create_app(db_path, needs_path)` working unchanged for existing tests):

1. `app.main.SYNC_INTERVAL_DEFAULT_MINUTES: int = 15`
2. `app.main.mailbox_should_sync(state: dict, *, now=None, sync_running: bool = False) -> bool`
   - Pure tick decision: returns `True` iff `state` indicates `auth_state == "valid"` and `auto_sync == "on"` and `sync_running` is False. (Interval is read from state elsewhere; this isolates the skip conditions the tests pin.)
3. `async app.main.mailbox_scheduler(*, get_state, run_sync, is_running, sleep, interval_seconds=None) -> None`
   - Coroutine loop used by the lifespan. Contract the tests pin:
     - Each iteration: `await sleep(<interval>)` where `<interval>` is `state.get("interval_minutes", SYNC_INTERVAL_DEFAULT_MINUTES) * 60` (read from `get_state()` each tick, not a literal). If `interval_seconds` is provided it may be used as an override, but the "runs at interval from state" case must read `interval_minutes` from state.
     - On each wake: if `mailbox_should_sync(get_state(), sync_running=is_running())` then call `run_sync()` (sync callable is fine if run off-thread by caller/impl; tests pass a plain function). If `is_running()` is True or state says skip, do not call `run_sync()`.
     - Exceptions raised by `run_sync()` (and error results) must NOT stop the loop/schedule; catch/log and continue.
     - Exits cleanly on `asyncio.CancelledError` (propagate after cleanup so the task is seen cancelled) with no leaked thread/warnings.
     - `get_state() -> dict|None`, `run_sync() -> Any`, `is_running() -> bool`, `sleep(seconds)` is an awaitable (tests inject to avoid real sleeps).
4. `create_app(db_path: str | None = None, needs_path: str | None = None, *, enable_mailbox_scheduler: bool = False) -> FastAPI`
   - Default `False` preserves current behaviour for all existing tests. When `True`, the FastAPI lifespan starts the scheduler task (every tick running `alerts_sync.sync` in a worker thread when valid+on) and cancels/awaits it on shutdown. The real app (e.g. `default_app`/CLI serve) should enable it.
5. Endpoint implementation hooks (optional but tests monkeypatch these names if present): `app.main.get_mail_source`, `app.main.delete_token`, `app.main.sync_mailbox`/`app.main.run_sync`. Authorise flow: tests monkeypatch `app.mailbox.oauth.authorize` and `app.mailbox.oauth.run_authorization`.

## Status codes chosen where `contracts/api.md` is silent

- `POST /api/mailbox/authorise` when mailbox not configured / cannot start: **409** `{"error": "mailbox not configured"}` (conflict with mailbox state; consistent with other conflict cases).
- `POST /api/mailbox/sync` when `auth_state == "not_configured"`: **409** `{"error": "mailbox not configured"}`.
- `POST /api/mailbox/sync` when `auth_state == "revoked"` or `auto_sync == "paused_auth"` (not authorised to sync): **409** `{"error": "sync not available: authorisation revoked"}` (clear 4xx; 409 chosen to match the "sync already running" conflict style).
- `PUT /api/mailbox/folder` invalid body (missing/empty/wrong-type `label_name`): **400**.
- (From contract, pinned explicitly) folder not found: **404** `{"error": "folder <name> not found"}`; sync while running: **409** `{"error": "sync already running"}`; authorise accepted: **202** `{"waiting": true}`; sync accepted: **202** `{"run_id": <int>}`.

Developer may choose 400 vs 409 for the two "not available to sync/authorise" cases if better justified, but must keep a clear 4xx and a clear error string; adjust tests in that case only with coordinator approval (tests-first rule). The values above are what these tests assert.

## Files

- `tests/test_api_mailbox.py` (new)
- `specs/001-alert-email-import/handoffs/T059-tests.md` (this handoff)

## How tests fail now (right reason)

Run (isolated env under `%TEMP%\casa-agent-T059-tests`, copied `needs.example.yaml`, `no_network` fixture): `python -m pytest -q tests/test_api_mailbox.py` -> **24 failed in ~12s**.
- Endpoint tests fail with **404 Not Found** on `/api/mailbox`, `/api/mailbox/authorise`, `/api/mailbox/folder`, `/api/mailbox/sync`, `/api/mailbox/disconnect` (missing endpoints/behaviour).
- Scheduler seam tests fail with **AttributeError** (`app.main` missing `SYNC_INTERVAL_DEFAULT_MINUTES` / `mailbox_should_sync` / `mailbox_scheduler`) and one **TypeError** (`create_app()` unexpected kwarg `enable_mailbox_scheduler`) — missing seams, as intended. No syntax/import-of-test-file errors.

`python -m compileall -q tests` -> exit 0.

`python -m pytest -q -m "not slow" --deselect tests/test_api_mailbox.py --co` collected **544/570 tests (26 deselected)** successfully. A full run of that deselected set was started but did not complete within the allotted time in this environment; I changed no `app/` files and only added a new test file, so existing tests are unaffected by this change.

## Decisions / notes not fully covered by docs

- **Scheduler tick function form:** `mailbox_scheduler` takes injected `get_state/run_sync/is_running/sleep` so tests avoid real sleeps/clocks/network and can assert "no sync call" without timing. `mailbox_should_sync` isolates the state predicates (valid+on, not running). Lifespan wires real state reader and runs `alerts_sync.sync` in a worker thread per R5/R6.
- **Interval source:** tests require reading `interval_minutes` from `mailbox_state` each tick (default 15) — not a literal — so the loop must consult state per wake.
- **Disconnect auto_sync:** data-model states `not_configured` via disconnect deletes token; tests accept `auto_sync` `on` or `off` after disconnect but not `paused_auth`.
- **Authorise non-blocking:** tests accept the background work completing via a thread/event; endpoint must return 202 immediately.
- **Sync run_id:** sync endpoint must return a run id; tests monkeypatch sync to return a summary including `run_id` and assert the endpoint surfaces an int `run_id` (it may come from `alerts.start_run` or the sync result; implementation should be consistent).

## For reviewer

- Confirm the chosen 409-vs-400 codes for not-configured/revoked sync (and not-configured authorise) match intended UX; they are explicit and documented above.
- Confirm `mailbox_scheduler` signature (keyword-only injected callables) is acceptable; it is the minimal seam to test interval/skip/error/shutdown without real time or network while keeping `create_app` default unchanged.
- `test_scheduler_clean_shutdown_no_real_sync` passes `enable_mailbox_scheduler=True` to `create_app`; developer must add this kwarg (default False).
