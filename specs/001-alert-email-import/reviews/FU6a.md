# Review 1: FU6a reprocess rules and failed-email excerpts (Tier A: import integrity, raw data kept)

Branch task/FU6a-reprocess-rules @ 90325c9, base jorgevr/spec-kit-3-feature. Read-only review by code reading, scratch
probes outside the repo (excerpt function only, no DB, no network), and the test suite. Isolation env vars under
`$env:TEMP\casa-agent\FU6a-review\`.

## Gates (each run once, foreground)
- `python -m compileall -q app tests`: pass
- `python -m pytest -q -m "not slow"`: 484 passed, 1 deselected
- `anonymise_eml.py --check tests/fixtures/emails`: exit 0
- forbidden-path diff: only app/alerts.py, two handoffs, tests/test_alerts_reprocess.py, tests/test_followups_reprocess_reasons.py
- `requirements.txt` diff: empty
- Tests: the only change to an existing test is the rename of `test_failing_reprocess_...` plus replacing `COUNT == 0` by
  "sighting rows identical to before" (two "before" lines added). Counts, failed outcome and `_listing(...) == before`
  untouched. Confirmed from the diff.

## Verified OK
### (1) Keep sightings on a non-imported re-read (app/alerts.py:352-368)
- DELETE of sightings, `touched`, `_record_sighting` and every `derive_listing` call are all behind `out.outcome == "imported"`.
  A failed/rejected re-read therefore touches no sighting, listing, field_sources, price_history, flags or sighting
  category. The UPDATE writes only the nine reprocess columns; raw, content_hash, first_run_id never written.
- Transaction: the whole body is inside `with conn:`; an exception in `derive_listing` (or anywhere) rolls back the UPDATE,
  DELETE, `_record_sighting` and `_count`. No helper in the loop commits. Intact.
- Repeat re-read: a failed/rejected row now carries the current `reader_version`, so scope `failed`
  (`reader_version IS NULL OR != current`) does not pick it again. Only an exception leaves the old version.
- imported -> failed -> imported: the second imported read takes `touched` from the kept sightings, deletes and re-adds them,
  re-derives; fine. Imported for another listing code: old sighting deleted, new listing created, old listing row stays
  (derive returns early on zero sightings), as pinned by a test and as in T044 F3; not changed by this task.
- Derivation does not filter by `alert_emails.outcome` (app/derive.py:46, main.py:66, scoring.py:364), so a kept sighting of a
  now-failed email keeps counting as a source and as an "Emails de alerta" entry. That is the user's decision (F3 keep).
- Counts: `_count` increments `n_<outcome>` and n_found together; the exception path does the same via
  `_count_file_failure`. n_found = imported + rejected + failed holds. The email list / `outcome` filter reflect the row,
  which now says failed while sightings exist.

### (2) Unexpected exception reason
- Reason is `type(exc).__name__` only (alerts.py:371); no message, path or text. Persisted by appending
  `{email_id, outcome: "failed", reason}` to `import_runs.notes` via the existing helper that import already uses for file
  failures; the notes keep the same JSON list shape and `run_detail` (main.py:235-242) already turns such entries into
  problems. The entry has no `text` key so it is not also shown as a notice. Counts +1 found/+1 failed, once.
- Missing date/subject: run_detail emits `alert_date: null, subject: null`; UI `importLines` (index.html:200) falls back to
  `sin fecha` and the email_id. No crash. Growth: one ~100 byte entry per exception per run, bounded by the number of
  emails; the whole list is re-serialised per entry (quadratic only in the number of failing emails, negligible).
- The email row and sightings stay as they were (rollback), so no row appears twice in run_detail.

### (3) Excerpt
- Only added to the "problems" and "anuncios en el email" failed reasons (alerts.py:150-151). Fixed phrases (not alert,
  unsupported, forward, text/plain, no date, file failures) are byte-identical (tests pin them). T043 substring
  `se esperaba X, encontrado Y` is intact: the excerpt is appended after it.
- Deterministic: pure function of the body (no clock, no randomness). Same reason on import and on reprocess.
- XSS: `convert_charrefs=True` decodes entities, so `&lt;script&gt;` survives as the literal text `<script>alert(1)</script>`
  (probe). Every UI sink escapes it with `esc` (index.html:200 `importLines`, the Emails list at :239, error lines). No
  sink for reasons without `esc`. Safe, but the API and the DB hold the raw text, so escaping at the sink is the only
  barrier (already the project pattern).
- Non-UTF8 / bad bytes: `get_content()` replaces undecodable bytes; no new exception. `read()` calls the same `_html`
  first, so anything that would raise already raised before the excerpt. An unclosed `<head>`/`<title>` hides everything and
  gives an empty excerpt (reason then unchanged), harmless. Parser errors are caught.
- Real fixtures: the excerpt is the start of the card (address, price, advertiser blurb), for example "Piso en Calle ...
  650.000 EUR. JJS HOMES vende en EXCLUSIVA ...". No household data in the first 120 chars.

## Findings

### F1 (medium, should fix): `_visible_excerpt` can take minutes on malformed markup (app/alerts.py:115-117)
`HTMLParser.feed` on a body of repeated unterminated start tags is super-quadratic. Probe (scratch, `_visible_excerpt` only):
`"<a " * 2000` (6 KB) = 1.05 s, `"<a " * 4000` (12 KB) = 9.55 s (about 9x for 2x), so 60 KB is minutes. Other shapes
(`<!--`, `<div`, `<![CDATA[`, `<!`, `<?`, `&`, long text, 25k tags) are linear/fast. The excerpt runs on every failed
Idealista-sender email at import and on every reprocess, with no timeout, so one malformed or hostile body (the sender must
match the Idealista address, so unlikely in practice) stalls the whole import/reprocess while it holds the single
connection. Only the first 120 visible chars are needed but the whole body is parsed. Fix: cap the HTML fed to the parser
(for example the first 8-16 KB, and test with the `<a ` shape) or strip tags with a bounded linear scan; add a test with a
hostile body and a time bound.

### F2 (low): excerpt privacy hardening (Articles III/IV)
- Length 120 is acceptable: it is a prefix of content already stored in `raw` in the same DB, and for the real shapes it is
  listing text. It is the advertiser's text, so a blurb could carry an advertiser phone or name; at 120 chars this is rare
  and not household data.
- Only `https?://\S+` is removed. Bare `www.` links, e-mail addresses and long digit runs (phones) survive. Consider also
  dropping `\S+@\S+` and `www\.\S+`. Not blocking.
- Control characters other than whitespace survive (probe: `\x1b[31m` and zero-width characters). The UI escapes HTML, but
  the CLI prints reasons (app/cli.py:50), so an ESC sequence from an email reaches the terminal. Consider removing
  `[\x00-\x1f\x7f]` after the whitespace collapse.

### F3 (low, informational): email row and its kept sightings diverge
After a failed or rejected re-read the row has the new `alert_type`/`search_name` (NULL for a non-alert/unsupported read),
`category` and `category_rules_matched`, while its kept sightings still carry the old `category`, and the "Emails no
importados" list shows an email that still supports a listing. That is the consequence of the user decision. scoring reads
`e.category = 'unknown'` for conflict rules (scoring.py:363-365), so a rejected re-read that sets the row to `unknown` with
matched rules could add a category-conflict flag for a listing the kept sighting still feeds. Rare (rules match on
search_name, which a rejected re-read usually clears). Optional: do not overwrite the category columns when keeping sightings.

### F4 (low): exception problem has no date/subject in run detail (main.py:241, alerts.py:371-376)
The immediate summary shows the real `alert_date`/`subject`; the persisted run detail shows null (the `subj` lookup uses
`first_run_id/last_run_id`, which this email's row does not carry). Cosmetic; a lookup by `email_id` would fix it.

### F5 (low, coupling): `reader._html` is private (providers/idealista_alert.py:160)
Acceptable (same package, one caller, and the excerpt sees exactly the HTML the reader judged). Recommend a public name on
the next provider touch.

## Verdict
Import integrity and raw data are kept: a not-imported re-read cannot change sightings or listings, the per-email
transaction still rolls back everything including `derive_listing` failures, exception reasons are class names only and
counted once, and the excerpt cannot inject HTML through the UI. All gates pass and the existing-test change is only the
deliberate one. F1 is a real availability defect on pathological markup and should be fixed (small); the rest are low.

STATUS: PASS
