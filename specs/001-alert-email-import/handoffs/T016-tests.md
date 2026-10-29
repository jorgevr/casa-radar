# T016 tests: import_paths

File: `tests/test_alerts_import.py` (no changes to `app/` or `tests/conftest.py`). All tests fail now with
`AttributeError: module 'app.alerts' has no attribute 'import_paths'`; the module imports cleanly.
The non-slow suite without this file still passes (72 passed).

## Tests
- `test_import_fixture_folder` (no_network): `import_paths(conn, [EMAILS])` gives found/imported/already/rejected/failed
  = 12/11/0/1/0, sum = found; exactly one problem with outcome `rejected` (alert_date starts 2021-03-10), none `failed`;
  11 rows in `listings`, each with price > 0, `area_m2` not null or `development` = 1, `url` starting
  `https://www.idealista.com/`; `n_new_listings` = 11; 12 `alert_emails` rows. Second import: 12/0/12/0/0,
  `n_new_listings` = 0, still 11 listings and 12 emails.
- `test_import_mbox_of_three_fixtures`: mbox built in tmp_path with `mailbox.mbox` from 3 fixtures (development,
  price drop, resale chalet) imports 3/3/0/0/0, 3 listings; `alert_emails.file_name` = `alerts.mbox#<index>`, distinct.
- `test_msg_file_is_reported_unsupported`: a `.msg` file (OLE magic bytes plus filler, not an email) gives a
  problem whose `reason` contains `unsupported file format: save as .eml`; 0 imported, 0 listings.
- `test_fixture_import_under_five_seconds` (`@pytest.mark.slow`): fixture import `< 5 s`, `n_found` = 12.

## Summary keys assumed (from data-model `import_runs` + api.md "run summary plus problems and notices")
`n_found`, `n_imported`, `n_already`, `n_rejected`, `n_failed`, `n_new_listings`, `problems` (list of dicts with
`email_id`, `alert_date`, `subject`, `outcome`, `reason`), `notices`. Plain dict, int counts.
`run_id`/`status` not asserted.

## Ambiguities
- The .msg problem's `outcome` and whether it counts in `n_found`/`n_failed`/`n_rejected` is unspecified; the test
  only checks the reason text appears in `problems[*].reason` and nothing is imported. Developer should pick one
  and document it (it must keep sum = n_found).
- `problems` entries for rejected emails: test relies on `alert_date` being an ISO string (as stored in
  `alert_emails.alert_date`).
- Listing "link" is read from `listings.url`; "area-or-development" from `area_m2` / `development`.
- "11 listings" assumes the 11 importable fixtures map to 11 distinct listing codes (as in the task text).
- Individual messages in the mbox are re-serialised by `mailbox.mbox` ("From " escaping may alter bytes), so only
  counts and file names are asserted there.
