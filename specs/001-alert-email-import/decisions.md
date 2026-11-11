# Decisions: T055–T059 (Gmail auth, source, sync, scheduler)

Status: accepted by the user. These decisions cover points the tests and docs leave open.
They do not change the spec or plan. Constitution articles I–X still override this file.

## T055: token store

- `load_refresh_token` returns a holder object exposing `.value`.
  - `__repr__` and `__str__` return `"<redacted>"`, so the token cannot leak into logs or test output (Art. III).
- `save_refresh_token` raises `ValueError` when `CASA_APPDATA` resolves inside the repository root.
  - Compare resolved paths.
  - The message never contains the token or the client secret.
- Refusing the real `%LOCALAPPDATA%\casa-radar` under test is applied only if the tests can express it. Otherwise it is out of scope.

## T056: OAuth

- Public functions:
  - `build_authorization_url(...)`
  - `exchange_code(..., transport=)`
  - `refresh_access_token(..., transport=)`
- `transport` is injectable. Tests stay offline through `no_network`.
- Results are plain dicts. The client secret is never logged or returned.
- A 401 on code exchange is accepted as `AuthRevoked` or `SourceUnavailable`.
  - The implementation raises `SourceUnavailable`, since there is no stored grant to revoke.
  - `AuthRevoked` is reserved for a 401 or `invalid_grant` on refresh. That case tells the user to re-authorise.

## T057: Gmail source

- Constructor: `GmailSource(client=<httpx.Client>, access_token=<callable>)`.
  - The callable lets the token refresh without rebuilding the source.
- The clock is used through module attributes (`import time; time.monotonic()`, `time.sleep()`), never `from time import ...`, so tests can monkeypatch it.
- Only the injected client makes requests. There is no global client.

## T058: `sync()`

- `sync()` returns a summary and does not raise on source errors.
  - Misconfiguration, such as an isolation violation, still raises.
- The summary always has this shape:

  | key | type | meaning |
  |---|---|---|
  | `status` | str | `ok`, `already_running` or `error` |
  | `n_found` | int | messages found |
  | `n_imported` | int | newly imported |
  | `n_already` | int | already imported |
  | `n_rejected` | int | rejected by the parser |
  | `error` | str or None | short code such as `auth_revoked` or `source_unavailable`; no message text |

- A concurrent call returns `{"status": "already_running", "n_found": 0, "n_imported": 0, "n_already": 0, "n_rejected": 0, "error": None}`.
  - It has no side effects and raises nothing.
- These keys and values are not pinned by the tests. They are recorded in the T058 handoff. Moving them into `contracts/` is a separate spec change for the user to approve.

### T058 addenda (user-approved after implementation)

- The summary may carry extra keys the tests require: `run_id`, `notice` (e.g. "folder identity changed"), and `message: "sync already running"` on refusal (`error` stays `None`).
- Folder-not-found uses error code `folder_not_found`; the Spanish text pinned by the tests goes in `mailbox_state.last_error`.
- Message order: `sync` keeps the order the source gives. `GmailSource` lists newest-first, so real syncs are not strictly oldest-first. Resuming still works because stored ids are skipped and the 2-day overlap re-lists recent mail.
- Two tests in `tests/test_sync.py` were wrong and were corrected with the user's approval: the duplicate `list_calls.append` in `BlockingSource`, and the `"old" not in fetch_calls` assertion in the 30-day test (Gmail applies `after` server-side).

## T059: scheduler

- The scheduler tick is covered by tests written first. They go beyond what `tasks.md` names, so they are listed as an extension in the handoff.
  - The tick does nothing while a sync is running.
  - The tick does nothing when the mailbox is not configured or authorised.
  - The tick never triggers a real sync.
- Tests inject a fake clock and a fake `sync`. They use no real sleeps.

## Open items for the user

- Confirm that the T059 skip tests are in scope, or add a task for them.
- Decide whether the T058 summary shape should move into `contracts/`.
