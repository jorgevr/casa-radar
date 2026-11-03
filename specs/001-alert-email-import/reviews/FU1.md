# FU1 review 2

Commit reviewed: d68c97b (diff base jorgevr/spec-kit-3-feature). Round 1 report kept as reviews/FU1-r1.md.

## Gates
- compileall: pass
- pytest -q -m "not slow": 341 passed, 1 deselected (150 s)
- anonymise check: pass
- forbidden-path diff: only app/alerts.py, app/categories.py, FU1 handoffs/reviews, tests/test_categories_hardening.py
- requirements.txt diff: empty

## F1 verification (fixed)
- load_rules uses `where = CATEGORIES_PATH.name` and `yaml.load(f.read(), Loader=_UniqueKeyLoader)`. PyYAML marks now read `in "<unicode string>", line N, column M`, so the line/column are kept and the path is gone.
- Probed by hand with a temp directory named `secretuser_*`: invalid YAML (flow and mapping cases), invalid UTF-8, bad entry, repeated key, and python-tag inputs all give ValueError messages with the file name only; none contains the directory. The directory-instead-of-file case (OSError) is covered by the new test and uses the file name plus exception class.
- import_runs.error is `ValueError: <that message>`, so it is clean too (test `test_import_error_column_has_no_absolute_path`).
- GET/PUT /api/categories wrap `str(exc)` of those same messages; PUT write failure already reports only the exception class. No path in any error body.
- Safety: `_UniqueKeyLoader` subclasses `yaml.SafeLoader`; `!!python/object/apply:os.system` and `!!python/name:` tags are rejected ("could not determine a constructor") and nothing is executed. construct_mapping still delegates to SafeLoader. The `_root` attribute is only used for the rule index.
- New tests assert `str(tmp_path)` and its parent are absent for YAML, UTF-8, entry and import-run messages.

## Regressions
None found: valid path unchanged, duplicate identical rules still load, UnicodeDecodeError from `f.read()` is still caught inside the try.

## Remaining notes (carried from round 1, not blocking)
- F2: mailbox sync path (`process_message` without `rules`) still raises on a malformed rules file; record a follow-up to load rules once in the sync loop with the same fallback, before the next phase checkpoint.
- F3: `contains` is not trimmed; recategorise_all raises on a malformed file (intended for an explicit user action).

STATUS: PASS
