# T060 follow-up: unexpected sync errors

## Change
- `app/cli.py` `_sync_command`: the `_run_sync(conn, _make_source(...), "sync_manual")` call is wrapped in
  `try/except Exception`. On any unexpected exception it prints
  `Sincronización detenida: error inesperado (<ClassName>).` to stderr and returns 2. The exception message
  and traceback are never printed. `BaseException` (KeyboardInterrupt, SystemExit) still propagates.
- With `--wait` the wait loop runs first and the same single guarded call follows; no second sync is started.
- `mailbox-setup` untouched.

## New tests (tests/test_cli_mailbox.py, class `TestSyncUnexpectedErrors`; no existing test changed)
- `test_run_sync_unexpected_exception_exits_2_class_name_only`
- `test_make_source_unexpected_exception_exits_2_and_sync_not_called`
- `test_wait_then_unexpected_exception_exits_2_single_sync`
- `test_keyboard_interrupt_from_run_sync_propagates` (passed before the change too: it pins existing behaviour)
Each error test plants fake tokens in the exception message and asserts the class name is in stderr, the
message, tokens and "Traceback" are not in stdout/stderr.

Red run before the fix: 3 failed (exception escaped), 22 passed. After: 25 passed.

## Gates
compileall OK; tests/test_cli_mailbox.py 25 passed; full `-m "not slow"`: 597 passed, 1 skipped, 2 deselected; anonymise check OK; no forbidden paths in `git diff --name-only main...HEAD`; requirements.txt diff empty.
