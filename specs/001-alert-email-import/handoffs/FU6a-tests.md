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

## Existing test changed deliberately (coordinator instruction, commit "FU6a: tests update for kept sightings")
- `tests/test_alerts_reprocess.py`: `test_failing_reprocess_does_not_blank_the_listing_an_earlier_import_made` renamed to
  `test_failing_reprocess_keeps_the_sightings_and_the_listing_an_earlier_import_made` (the old name said only "not blank").
- Why: user decision on review finding F3 (T044): "keep old sightings". The old assertion required the email's sightings to
  be deleted (COUNT == 0) after a failing re-read; that is the opposite of the decision.
- What: it now reads the email's sightings before the reprocess (one row) and asserts the rows are identical afterwards
  (replaced the `COUNT == 0` line, added the two "before" lines and a comment). The `_listing(...) == before` assertion, the
  counts, the failed outcome and everything else are unchanged. No other existing test was touched.
- Still stale (for the developer): the `reprocess` docstring in `app/alerts.py`, and the module docstring of
  `tests/test_alerts_reprocess.py` ("replaces the email's sightings"), which I did not edit.
- `test_email_that_still_fails_stays_failed_with_new_version_and_reason` has no prior sightings, so it is unaffected.

## Gates
Only the new test file was run (isolation env vars under `%TEMP%\casa-agent\FU6a`). No network, no real data.

## Excerpt hardening tests (review FU6a F1, F2; commit "FU6a: tests excerpt hardening")
Only `tests/test_followups_reprocess_reasons.py` changed (new helper `_card_removed_with_html`, section 3b).
- `test_hostile_markup_is_classified_quickly_with_a_bounded_excerpt[unterminated-a | unclosed-comments | unclosed-charrefs]`:
  a card-removed fixture with 320 visible characters at the start of `<body>` and about 200 KB of `"<a " * 70000`,
  `"<!--" * 50000` or `"&#" * 100000` appended after the last tag (so no later `>` can close the construct). Asserts
  (a) `store` of the email takes under 2 s (`time.perf_counter`); (b) failed, `se esperaba .+, encontrado .+` kept, whatever follows
  `encontrado ninguno` is at most 160 characters (120 of excerpt plus a short label), still starts as an excerpt
  ("palabra palabra"), no C0 control or DEL anywhere in the reason; (c) stored failed, raw byte for byte equal.
- `test_excerpt_drops_control_characters_bare_www_links_and_email_addresses`: visible text
  `Contacto<ESC>[31m ana@example.invalid www.example.invalid/x?a=1 y<BEL> fin`; the excerpt must keep "Contacto" and "fin" and have
  no C0 control, no `@`/`ana`, no `www.`/`example.invalid`; raw unchanged.
- Results on the current code: the control/www/e-mail test FAILS for the right reason (ESC survives in the reason, as does the
  address). `unclosed-comments` and `unterminated-a` run past the time limit: I ran them under `timeout` (60 s and 120 s) and
  both were killed with no result, so they fail (hang) rather than finish. A direct probe shows where: with 8000 `"<a "` the
  reader's `read` takes 0.01 s and `alerts._visible_excerpt` 48.8 s, so the whole cost is the excerpt's HTML parsing.
  `unclosed-charrefs` PASSES now (about 0.1 s, linear): it is a pin. Note for the developer/coordinator: until the fix is in,
  running the whole file hangs on those two cases, so run them with a timeout.
- Pitfall found while writing them: hostile markup placed BEFORE the real body is closed by the first real `>` and is fast; it
  must come after the last tag, as here.
