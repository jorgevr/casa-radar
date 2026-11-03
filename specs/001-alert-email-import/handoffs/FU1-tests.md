# FU1 tests: category rules hardening

File: `tests/test_categories_hardening.py` (new; no app code or existing tests touched).

## What the tests assert
- Extra keys in a rule are rejected (load and validate); message names the file and the 1-based index.
- Duplicate rule (same slug(contains) + same category, also after trimming category) is rejected; index of the
  second occurrence is named. Same contains with a different category stays allowed (categorise -> unknown).
- `contains` empty / only punctuation after slug() is rejected with index. (Empty and blank already were.)
- Category whitespace is trimmed by load_rules, validate_rules and save_rules (file content checked).
- OSError reading the file (a directory at the path) -> ValueError containing the filename, not the full path
  (neither tmp dir nor parent folder name).
- Import with a malformed rules file: `import_paths` does not raise, 3 fixture emails stored, all
  category 'unknown', rules matched '[]', sightings 'unknown', and import_runs.error starts with
  "ValueError: " and contains the file name and "invalid YAML".

## Status decision
Statuses in use are running / ok / failed ('failed' = run aborted and re-raised). The run completes, so the tests
expect status `'ok'` with `error` populated. A valid-rules run keeps `error` NULL (guard test).

## Current result (before implementation)
14 failed, 5 passed. The 5 passing are guards (blank contains, allowed same-contains/other-category,
accented contains, valid-rules import error NULL). Failures are missing behaviour (assertion on value or
PermissionError / ValueError not raised), not import errors.

## For the developer / reviewer
- Message for the import error must keep the full ValueError text (path allowed there; only the OSError
  wrapping must omit the full path). If you prefer the YAML/UTF-8 messages to also use filename only, the
  import test still passes (it asserts the file name, not the full path).
- Whether `contains` is also trimmed on load is not tested; trimming it is harmless.
- Isolation env vars were set under `%TEMP%\casa-agent\FU1\`.
