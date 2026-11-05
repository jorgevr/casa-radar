# FU6a tests: reprocess rules and failed-email excerpts

File: `tests/test_followups_reprocess_reasons.py` (new; `tests/reprocess_support.py` reused, unchanged; no existing test edited).
Run once: 5 failed, 5 passed. Each failure is a missing behaviour, not an import/syntax error.

## What each test asserts
1. F3 keep old sightings
   - `test_reread_that_is_not_imported_keeps_the_sightings_and_the_derived_listing[failed|rejected]` (FAILS now: sighting
     deleted). Two emails of one listing (645.000 then 630.000); the later one re-reads as failed (card removed) or rejected
     (other sender). Its sighting row is kept byte for byte, the listing is unchanged (price 630000), raw/content_hash unchanged,
     row records new outcome/reason/reader_version/last_run_id, summary problems list it.
   - `test_reread_that_is_imported_still_replaces_the_sightings` (pin, passes): imported re-read replaces the sighting (640.000/660.000).
   - `test_reread_imported_for_another_listing_code_replaces_the_sightings` (pin, passes): email re-read as listing 112658090:
     old sighting gone, new listing created, the OLD listing row (idealista:112842548) is NOT deleted and keeps its values
     (derive returns early on zero sightings), but has no sighting left as source. This is as-is behaviour; the test pins it.
2. Visible reason for an exception
   - `test_unexpected_exception_is_listed_in_the_run_detail_and_persisted` (FAILS now: problems list empty). Reader raises
     RuntimeError (message with a fake path) for one email; `GET /api/runs/{id}` lists exactly one problem for it, outcome
     `failed`, reason exactly `"RuntimeError"`, no message/path anywhere; the same after a new app/connection on the same db
     file; the email's stored outcome stays `imported`, last_run_id not the run, its sighting still there.
   - Schema: NO change required. `import_runs.notes` (JSON) already carries per-run entries, and `run_detail` already turns
     `{"email_id", "outcome": "failed", "reason"}` notes into problems (used for whole-file failures). Dev can append such a note
     in the except handler. Caveat for dev: run_detail's `notes` filter and `subj`/query must not list it twice or require an
     alert_emails row change. This test does not use `no_network` because its guard blocks TestClient's local socketpair
     (same reason test_reprocess_hardening requests its client fixture first); nothing in it can reach the network.
3. Excerpt
   - `test_failed_reason_carries_a_short_clean_excerpt_of_the_visible_text` (FAILS now): fixture with card removed plus injected
     visible text "Mira<nl><tab> https://example.invalid/x?a=1 <nl> y   http://otro.invalid/p fin" at the start of `<body>`.
     Reason keeps `se esperaba ..., encontrado ...`, contains `Mira y fin` (links stripped, whitespace collapsed), no `http`,
     no newline/tab/double space, longest run shared with the cleaned visible text between 40 and 120 characters, and neither
     the first 121 characters nor the whole text.
   - `test_failed_reason_of_the_plain_truncated_fixture_keeps_evidence_and_adds_text` (FAILS now): same bounds on the plain
     truncated fixture (marker renamed; keeps `0 tarjetas`).
   - `test_excerpt_is_deterministic_and_also_appears_when_reprocessing` (passes now trivially, becomes meaningful with the
     feature): same body, two Message-IDs, identical reasons; a reprocess under a newer reader yields the same reason.
   - `test_non_alert_reason_stays_exactly_the_fixed_phrase`, `test_other_fixed_reasons_stay_exactly_as_they_are` (pins, pass):
     non-alert (with a URL in its text), 2021 fixture (`tipo de alerta no soportado`), text/plain part (`formato sin muestra`)
     stay exactly the fixed phrases.

## Decisions the docs do not cover (dev must follow)
- The excerpt is a PREFIX of the visible text: HTML body only (no tags, comments, script/style/head/title), URLs
  (`https?://\S+`) removed, whitespace collapsed, then cut to at most 120 characters (an ellipsis counts inside the 120 or is
  not part of the checked run). Its position inside the reason is free, as long as `se esperaba X, encontrado Y` stays
  intact. If the dev includes `<title>` text first, the tests still pass for the injected case only if "Mira y fin" is still
  in the excerpt (it is, within 120 chars), but the 40..120 shared-run check compares against the test's own head-less text.
  If that is too tight, say so rather than loosening it.
- The forward and text/plain reasons are `failed` but fixed phrases: no excerpt.
- Multiple problems in one reason: the excerpt is appended once (tests do not constrain this).

## Existing test that contradicts decision 1 (NOT edited)
- `tests/test_alerts_reprocess.py::test_failing_reprocess_does_not_blank_the_listing_an_earlier_import_made` asserts
  `COUNT(*) FROM sightings WHERE email_id=? == 0` after a failing re-read (the old delete behaviour). It must be changed
  deliberately (the sighting is now kept; the listing equality assertion stays valid).
- Also stale: the `reprocess` docstring in `app/alerts.py` (F3 note of the FU5 review) and the module docstring of
  `tests/test_alerts_reprocess.py` if it states sightings are replaced for every re-read.
- `test_email_that_still_fails_stays_failed_with_new_version_and_reason` has no prior sightings, so it is unaffected.

## Gates
Only the new test file was run (isolation env vars under `%TEMP%\casa-agent\FU6a`). No network, no real data.
