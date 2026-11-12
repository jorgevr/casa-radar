# T059 dev handoff

## What changed (only `app/main.py`)

- Seams pinned by the tests: `SYNC_INTERVAL_DEFAULT_MINUTES = 15`, `mailbox_should_sync`, `async mailbox_scheduler(...)`,
  `create_app(..., enable_mailbox_scheduler=False)`, hooks `get_mail_source`, `delete_token`, `sync_mailbox`.
- FastAPI lifespan: when enabled, starts `mailbox_scheduler` as an asyncio task; on shutdown it cancels and awaits
  the task and closes the shared Gmail HTTP client.
- Scheduler: sleeps `interval_minutes` (state, else the constant) per tick, re-reads state, syncs only when
  `auth_state='valid'` and `auto_sync='on'` and no sync is running. The sync runs via `asyncio.to_thread` with
  kind `sync_scheduled`. Exceptions from a run are logged by class name and do not stop the loop; cancellation propagates.
- Endpoints: `GET /api/mailbox`, `POST /api/mailbox/authorise` (202 `{"waiting": true}`, OAuth flow in a daemon thread),
  `PUT /api/mailbox/folder`, `POST /api/mailbox/sync` (202 `{"run_id"}`, worker thread), `POST /api/mailbox/disconnect`.
- `GET` returns `reauthorise_steps` (Spanish list) only when `auth_state='revoked'`; `app_folder` from `credentials.app_dir()`.
  No secret is read or returned.

## Production wiring

`default_app()` in `app/main.py` now returns `create_app(enable_mailbox_scheduler=True)`. `app/cli.py serve` already runs
`uvicorn.run("app.main:default_app", factory=True, ...)`, so the real server starts the scheduler with no edit to `app/cli.py`.
Tests and every existing caller use `create_app(db, needs)` with the default `False`: no scheduler task.

## Decisions the docs do not cover

- `mailbox_state` has no `interval_minutes` column (`db.py` is not in scope), so the interval is the constant unless a
  state dict supplies the key; GET always reports it.
- Not-configured/revoked/paused sync -> 409 with clear errors (as pinned by the tests). Authorise never pre-checks: a failing
  flow (missing client secret, timeout, refusal) is recorded as `last_error` = "autorización no completada (<ExceptionClass>)"
  (class name only, never the message). On success: `auth_state=valid`, `auto_sync=on`, account best-effort via `account()`.
- Folder: AuthRevoked -> 409, SourceUnavailable -> 502, other errors propagate as 500. Creates the state row if missing.
- Disconnect: deletes the token, clears the access-token cache, sets `auth_state=not_configured`, `auto_sync=on`, account null.
- Sync workers (manual, scheduled, authorise) use their own sqlite connection, closed after; a per-app lock makes a second
  manual/scheduled sync return 409 / skip. `alerts_sync`'s process lock still applies below it.
- `run_id` of "sync now": the endpoint waits up to `RUN_ID_WAIT_SECONDS` (0.5 s) for the worker's real run id (summary or
  `running_run_id`). If the worker has not opened its run yet it returns the next rowid (`MAX(run_id)+1`), which is what
  `start_run` will get. Reviewer: check this fallback; it is the only inferred value.

## Reviewer checks

- Lock/connection handling in `mailbox_sync` (guard released in worker `finally`; thread start failure releases it).
- Cancellation path in lifespan; `_close_mail_client`.
- Fallback run id above.

## Gates

- compileall: ok. `tests/test_api_mailbox.py`: 25 passed.
- Full `pytest -m "not slow"`: 568 passed, 1 skipped, 2 deselected. anonymise check: ok. Diff vs main: no data/, config, secret, token or stray .eml files; requirements.txt unchanged.
