# T044 dev: alerts.reprocess

File: `app/alerts.py` only. `reprocess(conn, scope="failed"|"all")` returns the same summary shape as `import_paths`
(run_id, kind `reprocess`, status, n_*, problems, notices). Unknown scope -> `ValueError`, no run row.

## What changed
- Refactor with no behaviour change: the classification block of `process_message` became `_classify(msg, email_id,
  alert_date)` and the sighting insert + derive became `_record_sighting(...)`; both are shared with `reprocess`, so a
  re-read email is judged by exactly the same rules as a fresh one. `reader.read` / `reader.READER_VERSION` are used via
  the module attribute (monkeypatchable).
- `reprocess`: selects emails (scope failed: outcome `failed` or `rejected` with `reader_version` NULL or `<` current;
  all: every row), oldest alert first. Per email, one `with conn:` transaction: re-classify from the stored `raw`,
  delete its sightings, update `outcome, reason, reader_version, alert_type, search_name, alert_date, category,
  category_rules_matched, last_run_id` (never `raw`, `content_hash`, `first_run_id`), insert the new sighting if
  imported, `derive_listing` for the new listing and every listing the old sightings touched. Any exception rolls that
  email back, marks the run failed and propagates.
- Listings are never deleted; `derive_listing` returns early when a listing has no sightings left, so a listing whose only
  email stops reading is left as it was (choice 7). User-owned values are protected by `derive_listing` as before.

## The seven choices from the tests handoff
1. Scope failed = (failed OR rejected) AND older reader_version: the tests require a current-version failed email to be ignored, so the first draft (failed regardless of version) was wrong; fixed.
2. "Older" by string `<` (versions are `idealista-YYYY.MM`, lexicographic = chronological): confirmed; NULL counts as older.
3. Return shape like `import_paths`, `n_already` 0, `n_found` = emails re-read: confirmed.
4. ValueError on unknown scope: confirmed (API maps to 400).
5. Exit code 0/1 by `n_failed`: confirmed.
6. Plain list, column-named fields: confirmed.
7. Failing email keeps earlier listing: confirmed.
8. In-memory fixture mutations: nothing to challenge.
No test looked wrong.

## Reviewer checks
- `alert_date` is re-parsed from the stored Date header on reprocess (same value as at import).
- `category` is recomputed from current rules for every re-read email (consistent with FR-031); this goes beyond the task text.
- Re-reading with scope "all" counts `imported` for each re-read email, never `already`.
