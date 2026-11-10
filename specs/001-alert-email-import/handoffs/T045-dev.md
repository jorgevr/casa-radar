# T045 dev: reprocess-emails, stored-email endpoints

Files: `app/cli.py`, `app/main.py`.
- CLI `reprocess-emails [--failed|--all]` (mutually exclusive via argparse, default failed); prints `format_import_summary`
  lines; exit 1 if `n_failed > 0`.
- `GET /api/alerts/emails?outcome=failed|rejected|imported`: plain JSON list of `email_id, alert_date, subject, reason,
  outcome, reader_version`, newest alert first; other outcome -> 400.
- `GET /api/alerts/emails/{email_id:path}/raw`: `path` converter so Message-IDs with `/` work; 404 if unknown. Served as
  `application/octet-stream` with `X-Content-Type-Options: nosniff`, `Content-Disposition: attachment; filename="email.eml"`
  and `Content-Security-Policy: default-src 'none'; sandbox`, so stored HTML can neither render nor execute.
- `POST /api/alerts/reprocess {"scope"}`: 400 for missing/invalid scope or non-JSON body (not FastAPI's 422); response = run summary.
- Choices 4 and 6 of the tests handoff confirmed. The sync `def` list/raw handlers share the app's single connection like the other endpoints.
- Reviewer: the `{email_id:path}/raw` route must not shadow other routes (checked by the tests passing).
