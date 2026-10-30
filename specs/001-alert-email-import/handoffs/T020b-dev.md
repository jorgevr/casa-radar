# T020b dev handoff: file-level failures stored with the run

## What changed
- `app/alerts.py`: `_count_file_failure(conn, run_id, file_name, reason)` now also appends a tagged entry to
  `import_runs.notes` in the same UPDATE as the n_found/n_failed increment (same read-modify-write pattern as
  `_count`, committed immediately, so nothing is lost if a later message raises). `import_paths` passes
  `path.name` and the reason. The returned summary is unchanged in shape (`notes` still popped); the POST
  response still lists each file failure once (from the in-memory `problems`).
- `app/main.py` `run_detail`: notes entries with `outcome == "failed"` are returned in `problems`
  (`alert_date`/`subject` null, `outcome` "failed", `reason`); only entries with `text` feed `notices`, so a
  tagged entry never reaches the notices code. Raw `notes` is still popped.
- `data-model.md`: the `notes` row of import_runs only.

## Notes entry shape
Notice (unchanged): `{"email_id": <email id>, "text": <str>}`.
File failure: `{"email_id": <file name>, "outcome": "failed", "reason": <reason>}`.

## Decisions
- Discriminator: `outcome == "failed"` for failures, presence of `text` for notices.
- CLI untouched; it prints from the returned `problems`, so FALLO lines are not duplicated.

## Reviewer should check
- Notes write is atomic with the counters; no leak of raw `notes` in POST, GET run, GET runs list.
- Old runs (notes with only `{email_id,text}`) still render the same.
- No test edits.
