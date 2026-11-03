# FU1 dev: category rules hardening

Files: `app/categories.py`, `app/alerts.py` (tests untouched).

## Changes
- `validate_rules`: rejects unknown extra keys and `contains` whose slug() is empty; both name the 1-based entry. `category` is stripped on validate/load.
- Duplicate RULES are accepted (existing test relies on it). Instead `load_rules` uses `_UniqueKeyLoader`
  (SafeLoader subclass, `construct_mapping`) and rejects a key repeated inside one rule: ValueError with file name
  only, the key and the 1-based rule index.
- `save_rules` strips `category` on write.
- `load_rules`: `OSError` while reading -> `ValueError("<file name>: cannot read the file (<ErrorClass>)")`
  (no full path).
- `import_paths`: loads rules once; on `ValueError` uses `[]` rules (every email 'unknown', matched '[]') and, at
  the end, `finish_run(..., "ok", "ValueError: <full message>")`. `process_message` got an optional
  `rules` kwarg (default None = load from file as before, so other callers are unchanged).

## Reviewer should check
- The import error text keeps the full path (from the YAML/UTF-8 messages), as the tests handoff allowed; only
  the OSError wrapping omits it. This text is stored in import_runs.error and may be shown in the UI.
- `contains` is not trimmed (not tested); `recategorise_all` still raises on a malformed file (unchanged).
- Other `process_message` callers (mailbox sync) still load rules per email and would raise on a malformed file;
  out of scope for FU1's files.
- Existing rules files with repeated keys/extra keys/punctuation-only `contains` now fail to load.

## Known limitation
- The mailbox sync path (`process_message` without `rules`) still raises on a malformed rules file, aborting that
  sync. Only `import_paths` degrades to 'unknown' + `import_runs.error`.

## Review 1 fix (F1)
- `load_rules`: `where` is the file name only; the YAML is parsed from the read text (`yaml.load(f.read(), ...)`), so
  PyYAML marks say `<unicode string>` instead of the absolute path. Line/column are kept. All messages (YAML, UTF-8,
  bad entry, repeated key, OSError) and `import_runs.error` now carry the file name only.
