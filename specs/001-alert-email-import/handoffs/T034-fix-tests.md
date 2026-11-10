# T034 fix loop 1 tests: malformed category rules

File: `tests/test_categories_rules_file.py` (no changes to `app/` or existing tests). Source: review T034-r1 finding 1.
Rules file path is monkeypatched through `categories.CATEGORIES_PATH` to a tmp_path file; all offline.

## Tests
- Bad entry as the 3rd of 3 (two valid rules first): `pytest.raises(ValueError)`, message contains `alert_categories.yaml`
  and the digit `3` (after removing the full path from the message, so tmp_path digits cannot fake it).
  Cases: typo'd key (`categroy`), missing `contains`, missing `category`, values that are `""`, whitespace, `None`,
  an int or a list (8 parametrised), non-mapping entries (`"foo"`, `7`, `null`, a list).
- `test_typo_key_no_longer_changes_the_category`: review example, `categorise("Pisos y casas 123")` raises ValueError naming the file and position 1.
- Top-level not a list (mapping, string, int): ValueError naming the file (passes today).
- YAML syntax error and non-UTF-8 bytes: ValueError naming the file.
- `categorise` surfaces the error for any text.
- recategorise_all with a typo'd rule, a non-list file, a YAML syntax error: raises ValueError naming the file and the
  full snapshot of alert_emails, sightings and listings is identical (stale category kept). Non-list case passes today.
- Unchanged (pass today): missing file, empty file, comment-only file, `[]` give `[]` / `('unknown', [])`; valid file with
  a same-category duplicate gives `('flat', ['pisos','Pisos'])`, conflict gives `('unknown', [...3 texts in file order])`.

## Failure summary now
21 failed, 10 passed. 17 fail with `DID NOT RAISE ValueError` (silent drops), 3 with raw `yaml.parser.ParserError`,
1 with a raw `UnicodeDecodeError` message lacking the file name. Rest of suite (`-m "not slow"`, ignoring test_categories_api.py): 261 passed.

## Decision for the reviewer
An entry with an extra unknown key next to valid ones is NOT tested (brief does not require rejecting it).
