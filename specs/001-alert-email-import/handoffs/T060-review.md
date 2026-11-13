# T060 review — mailbox-setup and sync CLI

**Verdict: [PASS]** — no blocking findings. Non-blocking notes below.

Checked: `git diff jorgevr/Implementation...HEAD` (app/cli.py, tests/test_cli_mailbox.py, two handoffs). Ran with CASA_DB/CASA_NEEDS/CASA_APPDATA in `%TEMP%\casa-agent`:
`compileall` OK; `tests/test_cli_mailbox.py` 21 passed; `requirements.txt` diff empty; changed files = app/cli.py + tests + handoffs (no other hot file). No mailbox-setup/real sync/network was run.

## Tests-first
`git log --format=... -- tests/test_cli_mailbox.py` shows one commit only (aa53306, "T060: tests…"), before the dev commit f4a2f47. Tests were not edited afterwards. [OK]

## 1. Contract fidelity — OK
- mailbox-setup success prints the three contract lines: `app/cli.py:194-196` (`Cuenta:`, `Carpeta: {label} (id {folder_id})`, `Permiso: solo lectura de Gmail, revocable en myaccount.google.com/permissions`). Exit 0 (`:197`).
- sync: summary via `format_import_summary(detail)` + `Última sincronización correcta: {time}` (`:228-231`); exit `1 if detail["n_failed"] > 0 else 0` (`:232`); error → 2 (`:223`); already running → 3 (`:209`, `:219`, `:214`). Matches decisions.md.
- Non-blocking: the contract example's `13 sin cambios` is not printed; that is existing `format_import_summary` behaviour (T-earlier, "no 'sin cambios'" docstring `:52`), not T060.
- Non-blocking: "Última sincronización correcta" is omitted when `last_success_at` is empty (`:230 if last:`) — honest, fine.

## 2. Running-state rule and --wait — OK
- `_sync_is_running` (`:136-142`): true only if `running_run_id` set AND `import_runs.status == 'running'`; stale id with failed/ok run → false; missing run row → false. Matches the decision. Test `test_stale_running_run_id_not_running_does_not_count_as_running` covers it.
- `sync()` returning `already_running` → exit 3 (`:217-219`), no retry.
- No `--wait` → `:207-209` exit 3 at once, `_run_sync` not called.
- Wait loop `:210-215`: `deadline = _clock() + timedelta(seconds=SYNC_WAIT_TIMEOUT_SECONDS)`; `while _sync_is_running(conn): if _clock() >= deadline: … return 3; _sleep(SYNC_WAIT_POLL_SECONDS)`. Bounded, uses injected `_clock`/`_sleep`, sleeps 5 s per turn (no busy loop), constant read at call time (monkeypatch works). A cleared run exits the loop and `_run_sync` is called once (`:216`); no second sync while one runs.
- Non-blocking: deadline uses `datetime.now()` (wall clock, `:79-80`), not monotonic; a system clock jump could shorten/lengthen the wait. Acceptable for a 10-min CLI wait.
- Non-blocking (by user decision): a crashed process leaving a run with status `running` blocks `sync` (exit 3) until someone fixes it; only `--wait` timeout ends it. Documented decision, nothing for this task.
- Non-blocking: check-then-run is not atomic across processes (the real lock in `alerts_sync._LOCK` is in-process only). Two CLI processes could both start; inherent in the design (data-model says the real lock is in-process).

## 3. Secrets / tracebacks — OK
- Sync errors use fixed text per code `_SYNC_ERRORS` (`:71-76`) and the stored `last_error`/exception messages are never printed (`:221`).
- mailbox-setup handlers `:177-188` print fixed Spanish text; the catch-all prints only `type(exc).__name__` (`:186-187`).
- Account printed only if it fullmatches `[^\s@]+@[^\s@]+` (`:69`, `:189`), else `desconocida`; tests plant secrets and pass.
- Printed problem/notice lines carry stored email subjects/reasons — same as `import-emails` and contract; no raw bodies.
- Non-blocking: unexpected exceptions from `_run_sync` (`alerts_sync.sync` re-raises non-source errors, e.g. a bug or an unwrapped httpx error) or `_make_source` (`:216`) are not caught in `_sync_command` → Python traceback and exit 1 (indistinguishable from "email failed"). Not an "expected error", and tracebacks of exceptions here should not contain tokens (oauth exceptions carry method/path/status per mail-source contract), but a catch-all printing the class name and returning 2 would be more consistent with mailbox-setup. Suggest as a follow-up only.
- Non-blocking: `KeyboardInterrupt` at the interactive prompt (`:168`) gives a traceback. Trivial.

## 4. `_run_detail` (`:109-133`) — OK
- Line-for-line the same as `app.main.run_detail` (`main.py:378-401`): same queries, `first_run_id` vs `last_run_id` for reprocess, whole-file failures appended, notices with null date/subject when unknown. n_* come straight from the row (columns `DEFAULT 0`, `db.py:38-41`); nothing is imputed, absent subject/date stay null and `_problem_line` renders `sin fecha`.
- Drift risk: real but low-medium. The function in main.py is a closure inside `create_app` (can't be imported) and nothing tests the two stay equal; a later change to problems/notices shape in main.py would silently diverge from the CLI. Acceptable for now (the task could not touch main.py, a hot file); worth a later shared helper. Not demanded.
- Non-blocking: `json.loads(out.pop("notes") or "[]")` raises on corrupt notes (same as main.py).

## 5. Existing commands / lazy imports — OK
- No arg or branch changed for existing commands (`:238-283`, `:288-327` identical apart from the added elifs). `python -c "import sys, app.cli"` → httpx, `app.mailbox.oauth`, `app.mailbox.gmail`, `app.alerts_sync` all NOT loaded. httpx/oauth/gmail imported inside `_make_source` (`:98-99`), `_authorize` (`:92`), `_run_sync` (`:105`).
- Non-blocking: the new commands go through the shared preamble `db.connect()`, `seed_madrid_districts`, `db.load_needs()` (`:259-261`), so they also need a readable needs file; same as every existing command.

## 6. mailbox-setup flow — OK
- Order: label check → `_authorize()` → `_make_source` → `account()` → `resolve_folder(label)` (`:172-176`) → `INSERT OR IGNORE` row, then `write_state(provider="gmail", account, label_name, label_id, auth_state="valid", auto_sync="on", last_error=None, last_error_at=None)` (`:190-193`). Matches data-model transitions (not_configured→valid; revoked→valid with auto_sync := on) and main.py `authorise_worker`.
- No label + non-tty → nothing authorised, message `indica --label NOMBRE`, exit 2 (`:162-166`). Tty → prompt; EOF/blank → exit 2 without authorising (`:168-171`).
- Non-blocking: if authorisation succeeds but `resolve_folder` fails (`:180-182`), the token is stored but state is not updated (auth_state stays as before); user must rerun mailbox-setup (browser consent again). Defensible; maybe note in docs.
- Non-blocking: a non-email-shaped account is stored as NULL (`:189-193`), overwriting a previous account. Cosmetic.

## 7. Constants, deps, scope — OK
- `SYNC_WAIT_TIMEOUT_SECONDS = 600` and `SYNC_WAIT_POLL_SECONDS = 5` named (`:67-68`); `timeout=30.0` in `_make_source` (`:100`) is an inline literal for the http client (non-blocking; transport setting, not a rate/threshold).
- No new dependency; only app/cli.py among app files; tests use `no_network` and fakes, no browser.
- Non-blocking: `_make_source` creates an `httpx.Client` that is never closed (`:100`); short-lived process.

## 8. Test quality — mostly good, gaps (all non-blocking; tests must not be edited, so for a follow-up)
- Weak "or" assertions: `tests/test_cli_mailbox.py:166-167` (`"--label" in out or "--label" in err`, same for NOMBRE), `:257` (accepts `…11:45` or `…T11:45`), `:297` (`detail.lower() in … or "error" in …`, nearly vacuous).
- Not asserted: `auth_state == "valid"` / `auto_sync == "on"` / `last_error` cleared after mailbox-setup (`:138-155` only check label and output); account stored; interactive EOF/blank label; sync with no `mailbox_state` row (`cli.py:203-205`); `run_id` None / missing run (`:225-227`); first-run `INSERT OR IGNORE` of the row; notices rendering in sync output; `already_running` after a `--wait`; lazy imports.
- Fake clocks: `_clock`/`_sleep` are monkeypatched in both wait tests (`:355-356`, `:385-386`), so no real sleeping; timeout test shrinks the constant to 5 and the fake sleep advances time. The wait test asserts `polls >= 2` and one sync, so it fails without a real loop. Other tests would fail without the implementation (new subcommands/seams).
- `test_existing_commands_and_exit_codes_unchanged` (`:430-448`) is a thin regression check.

## Summary
All eight items satisfy the contract and user decisions; nothing blocking. Follow-ups worth considering: catch-all around `_run_sync`/`_make_source` returning a class-name message and exit 2; shared run_detail helper; extra tests for state transitions and the no-state/blank-label branches.
