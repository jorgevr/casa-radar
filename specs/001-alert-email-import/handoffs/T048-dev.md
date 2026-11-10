# T048 dev: first_run_id and new_since_last_run

## Changed
- `app/derive.py`: on INSERT only (existing is None), `first_run_id` = `alert_emails.last_run_id` of the newest (max rowid) sighting of the listing. UPDATE never writes it (NULL stays NULL, no backfill). Merge code untouched.
- `app/main.py`: `GET /api/listings?new_since_last_run=<bool>` (default false). Threshold = `MAX(run_id) FROM import_runs WHERE kind != 'reprocess' AND status = 'ok'`; keeps listings with `first_run_id` NOT NULL and >= threshold; no such run gives `[]`. Filter is applied to the ranked output (no rescoring), before `with_provenance`. Without the param: unchanged.
- `app/db.py`, `app/scoring.py`: not touched (`first_run_id` column already exists; `rank` copies the full listings row, so every listing carries it). SCORING_VERSION unchanged.

## Check
- Reprocess relies on `alerts.reprocess` updating `last_run_id` before `_record_sighting` (as stated by coordinator); tests for reprocess-created listings pass.
- Filter is in Python after ranking, not SQL, to keep ranks/scores of the full list.

## Gates
501 passed (full suite incl. slow, 20m46s); compileall OK; anonymise check OK; diff lists only T047 test files plus this change; requirements.txt diff empty.
