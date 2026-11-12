# T060 follow-up review

**[PASS]**

Scope checked: `git diff jorgevr/Implementation...HEAD` (3 files: app/cli.py, tests/test_cli_mailbox.py, handoffs/T060-followup.md).

## Findings (all OK)
- **Except scope**: app/cli.py:216-221 `try: result = _run_sync(conn, _make_source(conn, alerts_sync.read_state(conn)), "sync_manual")` / `except Exception as exc:`. Wraps only that one statement (both `_make_source` and `_run_sync`; the inline `read_state` argument is inside too, harmless). The already_running (:222), status error (:225), no-record (:231) and exit 0/1/3 paths (:213, :238, and the --wait timeout at :213) are outside the try, unchanged.
- **No message leaked**: `print(f"Sincronización detenida: error inesperado ({type(exc).__name__}).", file=sys.stderr)` (app/cli.py:219). Only `type(exc).__name__`; no `str(exc)`, args, repr, traceback, or logging.
- **Format**: fixed Spanish line, consistent with the existing "Sincronización detenida: ..." line (:227). stderr only.
- **Exit code**: `return 2` (app/cli.py:220).
- **BaseException**: clause is `except Exception`, so KeyboardInterrupt/SystemExit propagate; pinned by `test_keyboard_interrupt_from_run_sync_propagates` (tests/test_cli_mailbox.py, `pytest.raises(KeyboardInterrupt)`).
- **--wait**: wait loop (:208-215) runs before the single guarded call; after an unexpected error the function returns 2 with no retry or loop. `test_wait_then_unexpected_exception_exits_2_single_sync` asserts `calls["sync"] == 1`.
- **mailbox-setup untouched**: diff of app/cli.py is 5 added / 1 removed lines, all in `_sync_command`. (The pre-existing `except Exception` at :186 is not in the diff.)
- **Tests append-only**: `git diff --numstat` -> `101 0 tests/test_cli_mailbox.py` (zero deletions); app/cli.py `5 1`. No existing test or assertion changed.
- **Test quality**: `UnexpectedBoom.__str__` plants `FAKE_TOKEN`, `FAKE_SECRET` and "cuerpo del email"; `_assert_class_only` asserts class name in stderr, and "kaboom", the body text and "Traceback" absent from stdout+stderr, plus `_assert_no_secrets`. Covers `_run_sync` raising, `_make_source` raising (also asserts `_run_sync` not called), and --wait.
- **Fail without change (verified)**: copied HEAD into a temp dir with app/cli.py from `jorgevr/Implementation`: 3 failed (the three error tests, exception `UnexpectedBoom` escapes), 22 passed. With the change: 25 passed. The KeyboardInterrupt test passes both ways by design (regression pin, disclosed in the handoff).
- **No other files / deps**: `git diff ... -- requirements.txt` empty; no forbidden paths in the diff; working tree clean apart from this uncommitted review file.

## Minor notes (not blocking)
- `alerts_sync.read_state` is inside the try, so a DB error there also yields exit 2 with the class name; acceptable and arguably desired.
- The wait-loop `_sync_is_running`/`_sleep` calls are outside the try, so an unexpected error there still tracebacks; outside the requested scope.

Gates run (isolated CASA_* in temp): compileall OK; tests/test_cli_mailbox.py 25 passed. Full suite not re-run by reviewer (handoff reports 597 passed).
