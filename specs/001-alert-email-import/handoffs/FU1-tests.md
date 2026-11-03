# FU1 tests: category rules hardening

File: `tests/test_categories_hardening.py` (new; no app code or existing tests touched).

## What the tests assert
- Extra keys in a rule are rejected (load and validate); message names the file and the 1-based index.
- A key repeated inside one rule mapping (YAML text, e.g. two `category:` lines) is rejected with the file name,
  the key and the 1-based rule index. Two separate identical rules (same contains and category) must still load;
  different category with same contains also allowed.
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
see run below. The 5 passing are guards (blank contains, allowed same-contains/other-category,
accented contains, valid-rules import error NULL). Failures are missing behaviour (assertion on value or
PermissionError / ValueError not raised), not import errors.

## For the developer / reviewer
- Message for the import error must keep the full ValueError text (path allowed there; only the OSError
  wrapping must omit the full path). If you prefer the YAML/UTF-8 messages to also use filename only, the
  import test still passes (it asserts the file name, not the full path).
- Whether `contains` is also trimmed on load is not tested; trimming it is harmless.
- Isolation env vars were set under `%TEMP%\casa-agent\FU1\`.

## Correction (duplicate keys, not duplicate rules)
Duplicate-rule tests were replaced. Now: a key repeated inside one rule mapping (two `category:` lines, or two
`contains:`) in the YAML text must raise ValueError naming file, key and 1-based rule index (PyYAML otherwise keeps
the last value silently); identical separate rules (same contains + category) must still load.
Run against the code in this worktree: the two repeated-key tests fail with "DID NOT RAISE ValueError" (missing
behaviour). `test_same_contains_and_same_category_still_loads` fails only because the worktree's current
app/categories.py already rejects duplicate rules ("entry 2 duplicates an earlier rule"); that dev code must be
removed. Against the original code that guard passes. Needs a duplicate-key-detecting YAML loader (e.g. a
SafeLoader subclass overriding construct_mapping).

## Review 1, F1: absolute path in error messages
Four tests added at the end of `tests/test_categories_hardening.py`. For invalid YAML, invalid UTF-8 bytes, a bad
entry (missing `category`) and the `import_runs.error` column (invalid YAML), the message must contain the file
name `alert_categories.yaml` and neither `str(tmp_path)` nor `str(tmp_path.parent)`. All four fail now because the
message starts with the absolute path (and PyYAML marks `in "<path>"` repeat it). Fix needs the file name only in
`where` and the PyYAML problem_mark/context_mark text stripped or rebuilt (keep line/column, e.g. from
`exc.problem_mark.line/column` and `exc.problem`).
