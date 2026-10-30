# T020 dev: alert import and run endpoints

File changed: `app/main.py` only (no change to `app/alerts.py`: the stored run is read directly with SQL in main.py).
Imports added: base64, binascii, json, re, tempfile, Query, `alerts`.

## What it does
- `POST /api/alerts/import`: reads the JSON body, validates, decodes each file, writes it to a
  `tempfile.TemporaryDirectory` (system temp, outside the repo; one subfolder per file so duplicate names cannot
  collide), calls `alerts.import_paths(conn, paths, kind="file_ui")`, returns its summary. The directory is removed
  when the `with` block ends, also on exception.
- `GET /api/runs?limit=20`: newest first, each item the full run detail (summary + `problems` + `notices`).
- `GET /api/runs/{run_id}`: same shape; 404 `run not found` if unknown.
- Run detail = `import_runs` row without `notes`, plus:
  - `problems`: `alert_emails` rows with `first_run_id = run_id` and outcome rejected/failed
    (`email_id, alert_date, subject, outcome, reason`).
  - `notices`: parsed from `import_runs.notes`, enriched with `alert_date`/`subject` from `alert_emails`.

## Decisions the docs don't cover
- Malformed (400): body not JSON / not an object, `files` missing, not a list or empty, item not an object, `name` or
  `content_base64` not a string, invalid base64 (`validate=True`). Single fixed message
  `se esperaba {"files": [{"name": str, "content_base64": str}, ...]}`; never echoes names or content.
- Empty `files: []` -> 400 (nothing to import; avoids an empty run).
- Unreadable/unsupported extension in a well-formed body -> 200, counted as found+failed with a `failed` problem
  (alerts.import_paths behaviour). The POST response uses import_paths' own problems, which include these.
- File names are reduced to their last path segment and characters outside `\w . - space` become `_` (path
  traversal / Windows-invalid names); empty name becomes `file`. The extension still decides eml/mbox.
  Stored `alert_emails.file_name` therefore has the sanitised name.
- `limit`: default 20, accepted 1..500; otherwise FastAPI answers 422 (not 400).
- Limitation: for stored runs, file-level failures (unsupported extension, unreadable/empty mbox) are not in
  `alert_emails`, so `GET /api/runs/{id}` cannot list them as problems (the count in `n_failed` still shows them).
  Right after the POST they are present in its response. Also, "already" messages are not problems, and a message
  first seen in an earlier run is attributed to that earlier run only (`first_run_id`).
- No limits on body size or number of files, no duplicate-name check (unspecified).
- `kind` is `file_ui` (data-model).

## Reviewer checks
- Temp dir lifecycle and that nothing under the repo is written; messages never include file content.
- Notice enrichment relies on `notes[].email_id` matching `alert_emails` of this run (first/last_run_id).
- Gates: compileall 0; not slow 94 passed; slow 1 passed; anonymise check exit 0.
