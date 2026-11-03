# FU4 tests: malformed rules outside import_paths

File: `tests/test_sync_rules_fallback.py` (new; nothing else touched).

## What exists
`grep` of `app/`: `process_message` has one caller, `alerts.import_paths` (FU1: loads rules once, falls back to
`[]` + `import_runs.error`). No mailbox sync exists yet (Phase 9). Other `load_rules` callers (`cli categories`,
`main.categories_view`, `recategorise_all`) already report a clear error and are not email-processing loops.
So the sync loop is specified at `process_message` level: a caller that does not pass `rules`.

## Tests
- `test_process_message_without_rules_on_malformed_file_stores_unknown`: bad YAML, three fixture emails through
  `process_message` with no `rules`: no raise, 3 x imported, category 'unknown', matched '[]'. FAILS now
  (ValueError from `categorise` -> `load_rules`).
- `test_process_message_without_rules_on_unreadable_file_stores_unknown`: rules path is a directory (OSError
  wrapped as ValueError): same expectations. FAILS now (same reason).
- `test_process_message_without_rules_still_uses_a_valid_file` (guard, passes): valid rule `chalet` -> `villa`
  is still applied.
- `test_import_paths_loads_rules_once_per_run` (guard, passes): 3 emails, `load_rules` called once.
- `test_import_paths_with_malformed_rules_loads_once_and_error_has_no_local_path` (guard, passes): one load,
  status ok, error starts "ValueError: ", names the file, contains no tmp directory.

## Decisions / for the developer
- Likely fix: `process_message` (or `categorise`) catches ValueError when `rules is None` and uses `[]`. The
  "error recorded in import_runs.error, once per run" part for a future sync belongs to the Phase 9 sync task;
  it cannot be tested without a sync caller, so it is not specified here. `categorise(text)` with no rules and a
  malformed file is deliberately NOT specified (CLI `categories` relies on the raise).
- "Rules loaded once per run" for a future sync can only be asserted when that caller exists.
