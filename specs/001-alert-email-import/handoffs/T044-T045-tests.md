# T044, T045 tests: reprocess, reprocess-emails, stored-email endpoints

Files (new; `app/` and `tests/conftest.py` untouched):
- `tests/reprocess_support.py` - helpers, not a test module: fixture mutations in memory (card marker removed -> failed "0 tarjetas"; added text/plain part; a follow-up drop 645.000 -> 630.000 dated 2026-10-28), `store()` (public pipeline), `newer_reader()` (bumps `READER_VERSION` to `idealista-2026.11` and wraps `reader.read`), `snapshot()`.
- `tests/test_alerts_reprocess.py` (T044, 18 tests), `tests/test_cli_reprocess.py` (T045 CLI, 9), `tests/test_api_alerts_emails.py` (T045 API, 17 incl. parametrised).

## What is asserted
T044 `alerts.reprocess(conn, scope)`: failed email + newer reader that understands -> imported, reason cleared, version updated, raw/hash untouched, sighting and listing created (645.000); "failed" ignores current-version emails and imported ones; "failed" also re-reads old-version rejected emails; "all" re-reads everything, counts 3/1/0/1/1 sum to found; sightings replaced (not appended) and listing re-derived; still-failing email stays failed with new version and new reason, no sighting, earlier listing not blanked; fresh import vs (newest-first store + reprocess all) give equal listings/sightings/price_history, plus hand golden (price 630.000, first/last seen 10-26/10-28, price_updated_at 10-28, published_at null); manual/csv price and user new_build survive; idempotent for both scopes; an `import_runs` row kind `reprocess`, status ok, `last_run_id` updated, `first_run_id` kept; empty DB still records a finished run; unknown scope -> `ValueError` with no run row.
CLI: default == `--failed`; `--all`; summary lines in the existing `format_import_summary` text; exit 1 when an email fails; "0 emails..." summary; `--failed --all` refused by argparse (message "not allowed with argument").
API: list by outcome with keys exactly `email_id, alert_date, subject, reason, outcome, reader_version`; no raw in list; invalid outcome 400; raw byte-for-byte, content type in {message/rfc822, text/plain, application/octet-stream}; `sha256:` ids work; unknown id 404 (preceded by a 200 on the same route); POST reprocess failed/all summaries; invalid scope (`everything`, `""`, missing, null, int) and non-JSON body -> 400 and no run; read-only GETs; no secrets in bodies.

## Status on current code (one run)
46 collected before final tweaks: 42 failed, 4 passed; after tightening the 3 vacuous ones, they fail too (verified); the last one (secrets, tightened with 200 checks) fails now as well. So every test fails for missing behaviour: `AttributeError: module 'app.alerts' has no attribute 'reprocess'` (unit tests: the function is the thing under test, no cheaper observable), argparse "invalid choice" (CLI), 404 on the new routes (API; the `seeded` fixture itself uses the existing import endpoint and passes). No regression pins: nothing here passes on the current code.

## Decisions the docs do not cover (dev/reviewer please confirm)
1. Scope "failed" = outcome failed OR rejected with `reader_version` older. Reading: data-model "failed/rejected -> any".
2. "Older" assumed ordered by string (`idealista-2026.10` < `idealista-2026.11`); `!=` would also pass.
3. Return value = same shape as `import_paths` (run_id, kind `reprocess`, status, n_*, problems, notices); `n_already` 0; `n_found` = emails re-read.
4. Unknown scope: `ValueError` from `alerts.reprocess`; the API maps it (and missing/non-string scope, non-JSON) to 400. Contract only says 400 for a malformed import request; the brief says 400 for bad outcome/scope (FastAPI default would be 422).
5. Exit code of `reprocess-emails`: 0, or 1 when `n_failed > 0` (as `import-emails`); contract is silent.
6. List endpoint returns a plain JSON list (like `/api/runs`); item field names are the column names; raw content type must not be html (the contract names none).
7. An email that stops being readable keeps the listing a previous sighting made (FR-009/FR-011: nothing deleted or blanked) - `test_failing_reprocess_does_not_blank_...`; if the dev decides otherwise, say so.
8. Fixture mutations are in memory only; the follow-up drop is the anonymised fixture with two prices and the Date changed, verified to read as a normal drop.

## Reviewer checks
Gates run: compileall ok. Full `pytest -m "not slow"` and the privacy check were not run (tests only, as asked); `git diff` touches only tests/ and this handoff.
