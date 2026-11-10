# Review 1: FU5 reprocess hardening (Tier A: import integrity)

Branch task/P7-FU5-reprocess-hardening @ a6b6d51, base jorgevr/spec-kit-3-feature. Read-only review by code reading
plus the test suite; isolation env vars under `$env:TEMP\casa-agent\P7-FU5-review\`; no network, no real data.

## Gates (each run once, foreground)
- `python -m compileall -q app tests`: pass
- `python -m pytest -q -m "not slow"`: 474 passed, 1 deselected
- `anonymise_eml.py --check tests/fixtures/emails`: pass
- forbidden-path diff: only app/alerts.py, app/main.py, two handoffs, tests/test_reprocess_hardening.py
- `requirements.txt` diff: empty
- Tests untouched: `git diff bed99cb HEAD -- tests` is empty.

## Verified OK
- F5 transaction handling: `with conn:` (app/alerts.py ~L296) commits on success and rolls back on any exception, so the
  email's DELETE of sightings, the alert_emails UPDATE, `_record_sighting`, re-derives and `_count` all revert together.
  No helper in the loop commits (the only `conn.commit()` calls are in run start/finish and `_count_file_failure`, none on
  this path), so nothing partial leaks into the next email. The failure counting is a separate short `with conn`
  transaction; the connection is not left in a transaction. No savepoints needed.
- `except Exception`, not BaseException: KeyboardInterrupt/SystemExit propagate (outer `except Exception` also
  does not catch them; note a KeyboardInterrupt leaves the run row unfinished, same as before).
- Reason is `type(exc).__name__` only; no message, path or content. Counts: each id adds exactly one to n_found (via
  `_count` in the try or in the handler), so n_found = imported + rejected + failed (+ already, 0 here).
- F2: `rules=None` path keeps `row["category"]` and `category_rules_matched` (also passed to `_record_sighting`); the
  error text is the loader's `file-name: ...` message, no tmp path; run status `ok`, error noted. Valid rules still go
  through `categorise`, so categories update. Import path still falls back to `[]` (unchanged, no regression).
- F4: `reader_version IS NULL OR reader_version != ?`. A failed/rejected email re-read normally is written with the
  current version, so later scope `failed` runs leave it alone (no repeated re-reads). A downgrade re-reads
  older-than-code and newer-than-code rows alike (harmless, intended per task).
- F1: `run_detail` uses `last_run_id` for kind `reprocess`, `first_run_id` otherwise. Import runs are unchanged, and
  reprocess inserts no rows (UPDATE/DELETE only), so no duplicates arise when an email failed in run A and again in B:
  A's detail still lists it by first_run_id, B's by last_run_id.

## Findings (all low, none blocking)

### F1 (low): unexpected-exception emails are in the summary but not in `GET /api/runs/{id}`
app/alerts.py (handler) leaves the email row unchanged, so its `last_run_id` is not the reprocess run. The run's
`n_failed` counts it, but the stored run detail `problems` (app/main.py:239) omits it. Counter and list disagree for
that rare case (dev flagged this). Consequence of F4: such an email keeps its old reader_version, so every
scope `failed` reprocess re-reads it and counts it failed again (bounded, one cheap attempt per run; acceptable).

### F2 (low): run detail for a reprocess run is not stable history
A later reprocess C overwrites `last_run_id`, so run B's `problems` list shrinks to emails C did not touch. Counters in
B remain. Acceptable for a single-user tool; a per-run problems record would be the proper fix (out of scope).

### F3 (trivial): docstring of `reprocess` has an over-long, partly stale line (app/alerts.py ~L270)
It still says each email keeps "nothing is deleted" while sightings of an unreadable email are deleted (T044 F3, not
in FU5 scope). No code impact.

## Verdict
F5 rollback isolation, F2 category preservation, F4 selection and F1 run detail behave as specified; tests untouched and
all gates pass. Remaining notes are minor.

STATUS: PASS
