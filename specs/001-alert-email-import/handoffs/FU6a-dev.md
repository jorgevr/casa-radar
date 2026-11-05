# FU6a dev: reprocess rules and failed-email excerpts

File changed: `app/alerts.py` only (`app/main.py` and the provider needed nothing; no schema change, no new dependency,
SCORING_VERSION unchanged, tests untouched).

## What changed
1. F3: `reprocess` deletes/replaces an email's sightings and re-derives touched listings only when the new read is
   `imported`. A failed/rejected re-read keeps the sightings; the `alert_emails` row still records the new
   outcome/reason/reader_version/category/last_run_id.
2. Unexpected exception during a re-read: the email's transaction rolls back (row and sightings unchanged) and
   `_count_file_failure` appends `{email_id, outcome: 'failed', reason: <class name>}` to `import_runs.notes` and counts
   n_found/n_failed. `run_detail` already lists such notes as problems; no change in `app/main.py`.
3. Excerpt: new `_visible_excerpt` / `_failed_reason` in `app/alerts.py`. Applied only to the problems/"anuncios"
   failed reason in `_classify`: `<evidence>; texto del email: <excerpt>`. Excerpt = HTML body text without tags, comments,
   script/style/head/title, URLs removed, whitespace collapsed, first 120 chars. No HTML body: reason unchanged.
   Fixed-phrase reasons (including `REASON_NO_DATE`) are unchanged. Uses `reader._html` (a private helper of the provider).
4. `reprocess` docstring updated.

## For the reviewer
- The excerpt applies on import and on reprocess alike (same `_classify`).
- Exception notes use `_count_file_failure`, which commits inside the `with conn` block (harmless there).
- Hidden-tag depth is a simple counter; unbalanced markup can only hide or show more text in the excerpt.
- Because notes are not tied to an alert_emails row, the problem has alert_date/subject null in run detail.

## Gates (isolation under %TEMP%\casa-agent\FU6a-dev)
compileall ok; pytest -m "not slow": 484 passed; anonymise check ok; forbidden-path diff clean; requirements.txt diff empty.
