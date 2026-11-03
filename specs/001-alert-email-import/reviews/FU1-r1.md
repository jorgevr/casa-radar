# FU1 review 1

Commit reviewed: 7d2a5ee (diff base jorgevr/spec-kit-3-feature).

## Gates
- compileall: pass
- pytest -q -m "not slow": 337 passed, 1 deselected (207 s)
- anonymise check: pass
- forbidden-path diff: only app/alerts.py, app/categories.py, 2 handoffs, tests/test_categories_hardening.py
- requirements.txt diff: empty

## Checked and fine
- validate_rules: extra keys rejected (sorted, 1-based entry); `contains` empty after slug rejected; category stripped in validate, load and save.
- Duplicate YAML keys inside one rule rejected by _UniqueKeyLoader (message: file name, rule index, key); identical separate rules still load. Verified by hand for a 2-`category:` rule.
- OSError on read -> "alert_categories.yaml: cannot read the file (PermissionError)", filename only.
- import_paths: rules loaded once, ValueError -> rules [] -> every email 'unknown', matched '[]', run finishes status 'ok' with error "ValueError: <msg>". Valid path unchanged (rules passed explicitly, error NULL). `rules=[]` is not confused with None in categorise (`is None` test).
- main.py GET/PUT /api/categories, cli `categories` and recategorise_all still catch ValueError and use `str(exc)`; behaviour unchanged, only messages differ (new messages for extra keys / empty slug surface as 400 on PUT, as intended).
- No secrets or email content in the stored error.

## Findings

### F1 (should fix, cheap): full local path still leaks in YAML and UTF-8 errors
app/categories.py:48-55. `where = str(CATEGORIES_PATH)` is used for the "invalid YAML" and "not valid UTF-8" messages, and PyYAML also embeds the stream name in its marks (`in "C:\Users\<name>\...\alert_categories.yaml", line 2`). Reproduced with a temp file: the message contains the absolute path twice. With FU1 this string is now written to import_runs.error (alerts.py:215/240) and returned by GET /api/categories as a 500 detail and printed by the CLI. It includes the Windows user profile name, which is PII, and contradicts the "no full local path anywhere in messages" requirement.
Fix: `where = CATEGORIES_PATH.name`, and call `yaml.load(f.read(), Loader=_UniqueKeyLoader)` (string source, marks say `<unicode string>`) or strip the path from the mark text. Tests assert only the file name, so they will keep passing. Add one assertion that `str(tmp_path)` is absent in the invalid-YAML message.

### F2 (note, not blocking): sync path limitation
alerts.process_message called without `rules` (mailbox sync) still raises ValueError on a malformed rules file on every email. Judgement: acceptable for FU1 as scoped (file import is what the task names; sync is user-run and sync.py was out of scope), but record a follow-up: load rules once in the sync loop with the same fallback, otherwise a typo in the rules file aborts a real sync mid-run. The failure is loud, not silent data loss, so not blocking. Do not defer it past the next phase checkpoint.

### F3 (note): `contains` not trimmed; recategorise_all unchanged
Harmless (slug normalises). recategorise_all still raises on malformed file, which is the right behaviour for an explicit user action.

STATUS: FAIL
