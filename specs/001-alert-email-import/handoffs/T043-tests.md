# T043 tests: failed and rejected emails

File: `tests/test_alerts_failures.py` (no changes to `app/` or `tests/conftest.py`). Run once: 7 passed, 2 failed.
All emails are built in memory from anonymised fixtures by mutation (card removed, `Fwd:` subject,
`message/rfc822` attachment, added `text/plain` part, plain non-alert message). Nothing is written to the repo.

## Fail now (need T044 `alerts.reprocess`), reason `AttributeError: module 'app.alerts' has no attribute 'reprocess'`
- `test_reprocess_with_newer_reader_imports_failed_email` (US4-3): truncated price-drop is stored as failed; then
  `alerts.reader.READER_VERSION` is monkeypatched to a newer string and `alerts.reader.read` to return the real
  `ReadResult` of the intact fixture (no simple real layout change can be monkeypatched, so the newer reader is a
  stub of `read`). `alerts.reprocess(conn, scope="failed")` must: set outcome `imported`, reason NULL,
  `reader_version` = new one; leave `raw` and `content_hash` unchanged; create the listing and exactly 1 sighting;
  keep one `alert_emails` row; return a summary with `n_imported == 1`, `n_failed == 0`, `run_id`, and an
  `import_runs.kind == 'reprocess'` row. T044 must call `reader.read` / `reader.READER_VERSION` through the module
  attribute (as `process_message` does) for the patch to take effect.
- `test_reprocess_with_same_reader_leaves_failed_email_as_is`: assumption from T044 text ("reader_version older than
  the current one"): with an unchanged reader a failed email stays failed, same reason, no listing, `n_imported == 0`.
  If the developer reads `scope="failed"` as "re-read every failed email regardless of version", this test is the one
  to challenge (result would still be failed, so it should pass either way unless reprocess errors).

## Already pass (regression pins of existing behaviour)
- `test_failures_reported` (US4-1, US4-2, FR-009): after importing 2 valid fixtures, a non-alert is rejected with exactly
  "no es un email de alerta reconocido"; a truncated copy of an imported listing's email is failed with
  `se esperaba X, encontrado Y`; raw kept byte for byte; no listing/sighting row created or changed (full table snapshots).
- `test_failures_listed_in_import_summary`: folder of valid + non-alert + truncated: counts 3/1/1/1, problems list both with reasons.
- `test_2021_fixture_rejected_as_unsupported`: rejected "tipo de alerta no soportado", raw kept, nothing created.
- `test_forward_and_text_layouts_fail_without_listing` (3 params: `Fwd:` subject, `message/rfc822` attachment, added
  `text/plain`): failed "reenvío sin muestra" / "formato sin muestra"; forwarded flag 1 / 0; nothing changed (FR-017).
- `test_forward_and_text_layouts_on_empty_database`: same three on an empty DB create no listing or sighting.

## Notes for reviewer
- Removing the card also removes the titled listing link, so the reader's first reported problem is "título del
  anuncio ... ninguno", not "tarjeta". The test only requires `se esperaba <x>, encontrado <y>` evidence. The reader's
  `found` text is "ninguno"/counts rather than a raw excerpt; US4-2 asks for "what was expected and not found", which
  that satisfies. If an excerpt of the email is wanted, that is a reader change outside this task.
- Expected values (reason strings, counts) come from the spec/task text and the fixture set, not from code output.
