# FU5 tests: reprocess hardening (review T044 F1, F2, F4, F5)

File: `tests/test_reprocess_hardening.py` (new; reuses `tests/reprocess_support.py`; no existing test edited). F3 not specified.
Run once: 4 failed, 1 passed.

| Test | Asserts | Now |
|---|---|---|
| `test_reprocess_run_detail_lists_its_problems` (F1) | `GET /api/runs/{reprocess run}` `problems` lists the still-failing email with reason ("0 tarjetas"), kind `reprocess` | FAILS: problems `[]` (query uses first_run_id) |
| `test_import_run_detail_still_lists_its_problems` (F1) | import run keeps listing its failure by first_run_id, even after a reprocess | passes (pin) |
| `test_malformed_categories_file_keeps_stored_categories` (F2) | with a malformed rules file, scope all keeps email and sighting category `house` and `category_rules_matched`; run status `ok`; `import_runs.error` starts `ValueError: `, names `alert_categories.yaml`, no tmp path | FAILS: category becomes `unknown` |
| `test_failed_scope_compares_versions_by_difference_not_string_order` (F4) | with current `idealista-2026.10`: failed email stored `idealista-2026.9` and one with NULL are re-read (n_found 2, reader_version = current, last_run_id = run); current-version one untouched | FAILS: n_found 1 (2026.9 skipped) |
| `test_unexpected_reader_exception_does_not_abort_the_run` (F5) | reader raising RuntimeError for the middle email: no exception; n_found 3 = 2 imported + 1 failed; earlier and later emails get last_run_id; failing email keeps outcome/reason/version/category/raw/sightings; problem entry reason contains `RuntimeError` and the message text appears nowhere in the summary; no open transaction | FAILS: RuntimeError propagates |

## Decisions the docs do not cover (dev may challenge)
- F2: chosen behaviour is "keep stored category" (not abort); status `ok` plus error note, as import does.
- F5: reason is the exception class name only (review wording), put in the summary `problems`; the email row itself is not changed, so there is no DB column for the reason beyond the run summary. Run status is not asserted.
- F4: `!=` semantics (a downgrade also reprocesses), per the task text.
- F1: the pin test for import runs asserts the failing email still shows after a reprocess.
Setup mutates `reader_version` with a direct UPDATE (test data only).
