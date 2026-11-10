# T047 tests: new since the last run

File: `tests/test_alerts_new_since.py` (tests only; no app code, no tasks.md change).

## Behaviour pinned (coordinator decisions, repeated in the module docstring)
1. `listings.first_run_id` = run in which the listing's first sighting was stored; set on creation from a sighting, never changed afterwards (re-derivation, later runs, reprocess). Reprocess-created listing gets the reprocess run id. Listings without a sighting keep NULL, also after a later alert for them.
2. `GET /api/listings?new_since_last_run=true` = first_run_id NOT NULL and >= id of the latest run with kind != 'reprocess' and status = 'ok'; no such run -> `[]`. Absent/false -> all listings.
3. Every listing in the response has `first_run_id`.

## Tests
- `test_new_since_last_run`: batch A = 112842548, 112923327, 112899473; batch B = repeat sighting of 112842548 (`followup_drop`, new Message-ID) + 112921923, 112477754, 112887282. Filter after B == the three B listings; 112842548 excluded and keeps A's run id. Listing id = `idealista:` + code at the end of each fixture file name (derivation in the docstring).
- `test_param_absent_or_false_returns_all_listings`, `test_first_run_id_is_in_every_listing_and_set_on_creation`, `test_no_runs_gives_empty_list`, `test_only_a_failed_run_gives_empty_list`.
- `test_failed_run_is_skipped_when_choosing_the_last_run`: later `failed` and `running` runs (rows inserted in `import_runs` directly) do not change the baseline.
- `test_reprocess_keeps_first_run_id_of_existing_listings` (scope all, newer reader version).
- `test_reprocess_created_listing_after_last_import_counts_as_new`, `test_reprocess_before_a_later_import_is_not_new`.
- `test_manual_listing_is_never_new_and_a_later_alert_does_not_set_first_run_id`: a POSTed manual listing, plus a manual-source row inserted by SQL under id `idealista:112899473`, then the alert for it is imported: both keep NULL; only the really new listing is in the filter.

## Decisions / things to check
- Run ids are read from the run summaries (`run_id`), never hard-coded.
- Merge keeping `first_run_id` is NOT tested (merge body/flow not exercised here); the Developer should simply not touch the column in merge.
- The manual-listing test inserts a minimal `listings` row by SQL (id, source, url, title, price, first_seen, last_seen); if derive needs other columns on an existing row, that test may fail for a reason other than first_run_id: check.
- Reviewer: confirm the file-name code equals the listing id for each fixture used (the tests assume it, as DROP_LISTING/NEW_NAME do elsewhere).
