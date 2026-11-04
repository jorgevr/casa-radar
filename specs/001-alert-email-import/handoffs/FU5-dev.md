# FU5 dev: reprocess hardening (review T044 F1, F2, F4, F5)

Files: `app/alerts.py` (reprocess), `app/main.py` (run_detail). Tests untouched; F3 behaviour untouched; index.html untouched.

- F1: `run_detail` selects problems with `last_run_id` for kind `reprocess`, `first_run_id` otherwise.
- F2: on a malformed rules file `reprocess` uses `rules=None` and keeps each email's stored `category` and
  `category_rules_matched` (also written to the new sighting); run status `ok`, `error="ValueError: <message>"`
  (the loader's message names the file only).
- F4: scope `failed` is `reader_version IS NULL OR reader_version != current`.
- F5: each email is wrapped in try/except Exception. `with conn` rolls that email back; then a separate
  transaction counts it as failed (n_found+1, n_failed+1) with reason = exception class name only. The email row is
  not changed (no DB column for the reason; it lives in the run summary `problems`). Later emails continue; the
  run ends `ok`. Exceptions outside the per-email loop still mark the run failed and re-raise.

Decisions to check: the run status is `ok` even when emails hit unexpected exceptions (as for ordinary failures);
a failure reason for an exception exists only in the returned summary, not in `GET /api/runs/{id}` problems
(that lists the stored email's outcome/reason, which are unchanged).
