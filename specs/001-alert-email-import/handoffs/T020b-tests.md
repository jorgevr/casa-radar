# T020b tests: file-level problems stored with the run

File: `tests/test_run_file_problems.py` (new; no change to `app/`, `conftest.py` or existing tests).
Design (decided by the user): whole-file failures are stored with the run (in `import_runs.notes`, tagged as
failures) and returned by `GET /api/runs` and `GET /api/runs/{id}` in `problems` (`outcome` "failed",
`email_id` = file name, non-empty `reason`, `alert_date` and `subject` null), never in `notices`. The raw
`notes` JSON is not asserted. Expected counts by hand from the task text (e.g. valid + .msg = 2/1/0/0/1).

Result now: 8 failed, 1 passed (9 cases). Non-slow suite without this file still passes.

## Tests
- `test_file_failure_is_stored_and_listed_in_run_detail` (3 params: `alerta.msg`, empty `vacio.mbox`, an .eml saved
  as `guardado.mbox`): POST one file; `GET /api/runs/{id}` has counts 1/0/0/0/1, exactly one problem (failed,
  email_id = name, reason non-empty, date and subject null), `notices == []`; the `GET /api/runs` item for the
  run shows the same. FAILS now: `len(problems) == 0` (assert 0 == 1).
- `test_mixed_run_counts_add_up_and_failure_listed_once`: valid fixture + `.msg`: 2/1/0/0/1; the POST response
  lists the file failure exactly once; the stored run too. FAILS now at the stored run (0 problems). The
  POST-response part (once, no duplicate) already holds today (asserted first, passes).
- `test_rejected_email_and_file_failure_are_both_stored`: 2021 fixture + `.msg`: 2/0/0/1/1; stored problems are
  exactly 2 (one rejected with 2021 date, one failed file failure; order not asserted). FAILS now: 1 == 2 (only
  the rejected email is stored).
- `test_import_paths_missing_path_listed_once_and_readable_later`: `alerts.import_paths` on a missing path: its
  returned problems list it once (passes now); then `GET /api/runs/{id}` lists it (kind `file_cli`). FAILS now at
  the stored run. Sharing: the test opens its own `db.connect(tmp/t.db)` connection to the same file the API
  client's app uses (simplest option that works; SQLite file, committed writes visible across connections).
- `test_notices_are_unchanged_by_file_failures`: no fixture yields a notice, so the 23 Oct price-drop fixture is
  edited in memory (`6 hab.` -> `6 hab.     2 baños`, as T008) and posted with a `.msg`: the run has exactly one
  notice (the "2 baños" one, tied to its email with a subject) and exactly one problem, the file failure, which is
  not in `notices`. The notice assertions pass now; it FAILS at the stored problems (0 == 1).
- `test_same_missing_path_twice_gives_two_runs_each_with_its_own_failure`: two `import_paths` calls; each run
  lists exactly its own failure (no leakage; a later clean run has `problems == []`). FAILS now (0 == 1).
- `test_cli_summary_prints_one_fallo_line_per_file_failure`: `cli.main(["import-emails", bad.msg, missing.eml])`
  with utf-8 stdout: exit 1, exactly one `FALLO` line per file (2 total), totals line `2 emails: ... 2 fallidos`.
  PASSES now (the CLI prints from the `import_paths` return, which already works); it guards against a duplicate
  once the implementation also adds stored failures.

## Notes for the developer
- Keep `client` before `no_network` in test arguments (T017-tests.md).
- Whatever is stored must not make `import_paths` return the failure twice, and must not appear in `notices`
  (the existing notice mapping reads every `notes` entry as `{"email_id","text"}`: a tagged entry would
  otherwise be rendered as a notice with a KeyError/None text).

## Gaps
- Raw `notes` shape and the order of `problems` are not asserted. Folder expansion errors and multi-file
  failures in one run (two distinct bad files) are covered only by the CLI test (2 failures, not via the API).
- Two files with the same name in one run are unspecified, not tested.
