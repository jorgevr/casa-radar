STATUS: [PASS]

Re-review (iteration 2, commit b72a497) of `tests/test_sync.py`, from the actual file and `git diff 2f0f0bf HEAD -- tests/test_sync.py`, against T053/T058, contracts/mail-source.md and research R5/R6.

Run (offline, CASA_* under `%TEMP%\casa-review-T053`): `pytest tests/test_sync.py -m "not slow"` → 11 failed, 1 deselected: 7× `ImportError: cannot import name 'alerts_sync' from 'app'`, 4× `ImportError: cannot import name 'mailbox' from 'app'` (tests that touch `_mailbox_mod()` first). `-m slow` collects and fails the slow test (`test_thousand_message_backlog_under_ten_minutes`) with the same import error. `compileall` of the file is clean. Both causes are the accepted missing-module reasons; no syntax, fixture or existing-code import problem.

Scope: `git diff main...HEAD --name-only` = `tests/test_sync.py`, `handoffs/T053-tests.md`. The iteration-2 diff touches only `tests/test_sync.py` (and the handoff); nothing under app/, conftest, requirements, config, data; no secrets/.eml.

## Previous blocking defects

**F1 resolved: new-message test (tests/test_sync.py:242-263).** It now holds back `held_idx = next(i for i, p in enumerate(FIXTURE_FILES) if "2021" not in p.name)` (:245), i.e. index 1 (`2026-07-20_nueva-obra-nueva_..._112038902.eml`), which I verified imports (imported 1 / rejected 0 when run alone through `import_paths` in a scratch in-memory db). The 12 fixtures have 12 distinct `Message-ID` headers (grep count), so it is content-distinct from the 11 already stored. Assertions: `second["n_found"] == 1`, `second["n_imported"] == 1`, `second["n_already"] == 0`, `second["n_rejected"] == 0`, `after == before + 1` (:258-263). Correct against the task ("new message → imported, summary counts only it"). The held message keeps its `date` (yesterday, inside the window) and the same key scheme, so the sync finds it as the only new id.

**F2 resolved: no more raise pinning.** The four `assert isinstance(exc, mailbox....)` lines are removed from the interruption (:298 block), auth-revoked (:331), folder-not-found (:350) and source-unavailable (:371) tests; `grep isinstance` now matches only the `_contains_refusal` helper (:148-152). Each of those tests binds `_, exc = _invoke_sync(...)` and asserts only persisted state/calls: interruption `last_attempt_status == "failed"`, exact stored ids `{"msg00","msg01","msg02"}`, resume `n_found == 9`, `last_attempt_status == "ok"`, `last_success_at is not None`; revoked `auth_state == "revoked"`, `auto_sync == "paused_auth"`; folder `last_error == "carpeta Idealista no encontrada"`, `last_attempt_status == "failed"`, zero `alert_emails` rows, `list_calls == []`, `fetch_calls == []`; unavailable `auth_state == "valid"`, `auto_sync == "on"`, `last_error` truthy, `last_attempt_status == "failed"`.

## Decision A holds for every `_invoke_sync` user

`_invoke_sync` (:131-142) returns `(summary, None)` or `(None, exc)` and catches only `(AuthRevoked, FolderNotFound, SourceUnavailable)`. Success-path tests assert `exc is None` (:188, :216, :231/:236, :249/:256, :275, :309, :428/:422, :480), which is correct because they have no failure injected. The four failure tests no longer constrain raise vs return. The thread wrapper's `except Exception` (:398) only records `first_unexpected`, which is asserted None (:421) or re-raised (:411), so nothing is swallowed. Minor, non-blocking: the bound `exc` in the four failure tests is now unused (cosmetic; no linter is in the project).

## Other checks (unchanged, re-verified)

- Window test: `backfill_from=None`, `respect_after=False`, `list_calls[0][1] == today - timedelta(days=30)`, `"old" not in src.fetch_calls`, `stored == {"recent"}`, `st["backfill_from"] == (today - 30d).isoformat()` (:202-223). Its "recent" message is the rejected 2021 fixture (suggestion only: use an importable one).
- Second sync: `len(src.fetch_calls) == 12` and the id set (:237-239).
- Concurrency (:382-434): returned, not raised: `second_exc is None`, `_contains_refusal(second_result)` for the exact `"sync already running"`, one list call, 12 fetches, full first-sync accounting.
- `out_of_date` (:437-463): failed/stale/fresh plus exactly-30-min False, 30 min + 1 s True, failed-with-fresh-success True.
- Slow test (:466-485): 1,000 content-distinct messages, `n_found == 1000`, `n_imported + n_already + n_rejected == 1000`, `n_failed == 0`, `elapsed < 600`, `@pytest.mark.slow`.
- Offline: every test takes `no_network`; in-memory fake; no tautologies, no skip/xfail.
- Constitution: no rate/threshold literals in logic (30/30/600 are spec expectations); Article VI: only real fixtures, Message-ID changed in memory.

## Open decisions for the user (kept)

- **(A)** Does `alerts_sync.sync()` raise the named errors (`AuthRevoked`, `FolderNotFound`, `SourceUnavailable`) or return a failed summary? Docs say only "stop; error recorded". Tests accept either; decide before T058.
- **(B)** "Scheduler skips when `auth_state='revoked'`/`auto_sync='paused_auth'`" (T053 text, FR-029, US1-8) has no test here; it belongs to T059 (`app/main.py` lifespan predicate) and must be covered by a T059 test. Confirm who writes it.
- **(C)** The shape of the "sync already running" return (bare string, summary key, status field) is undocumented; the test accepts the exact string anywhere in the returned value.
- **(D)** `out_of_date(state, now)` state shape (dict-like with `last_attempt_status`, `last_success_at` naive ISO) and the behaviour for a never-synced state are undocumented; the summary keys `run_id/n_found/n_imported/n_already/n_rejected/n_failed` are mirrored from `import_paths`.
