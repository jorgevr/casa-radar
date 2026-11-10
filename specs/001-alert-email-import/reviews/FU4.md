# Review FU4 (round 1)

Diff: app/alerts.py (+5), tests/test_sync_rules_fallback.py, two handoffs. No other files.

## Checks
- process_message with rules=None: loads rules, catches only ValueError (malformed YAML, bad entries, unreadable file are all wrapped as ValueError by load_rules), falls back to [] so the email is stored as unknown with matched '[]'. Other exceptions propagate.
- Valid rules still applied (guard test).
- import_paths unchanged: loads once per run and records the error in import_runs.error; error carries file name only, no local path (tests assert).
- categorise(text) unchanged and still raises on a malformed file (CLI relies on it).
- Tests are offline (no_network), expected values hand-derived; two tests fail before the fix per tests handoff.
- No path leaks, no secrets, no data/config/.eml changes, requirements.txt diff empty.

## Gates
- compileall: ok
- pytest -q -m "not slow": 359 passed, 1 deselected
- anonymise check: ok
- forbidden-path diff: only the four files above
- requirements diff: empty

## Findings
- Note (non-blocking, already in dev handoff): the fallback re-reads the rules file per message and does not report the error; Phase 9 sync must load once per run and record the error. Acceptable as a safety net.

STATUS: PASS
