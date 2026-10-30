# T017 tests: alert import API (+ T020 companions)

File: `tests/test_api_alerts.py` (no changes to `app/` or `tests/conftest.py`). Client built as in test_core
(`TestClient(create_app(tmp/t.db, tmp/needs.yaml))`), fixture `no_aliases` as in T016. All 16 cases fail now with
`404 Not Found` (endpoints missing); module imports cleanly. Non-slow suite without this file: 78 passed.

## Tests (expected values by hand from tasks/contract)
- `test_api_import` (no_network): POST 2 fixtures (22 Oct new-build, 23 Oct price drop) as base64 JSON -> 200,
  found/imported/already/rejected/failed = 2/2/0/0/0, `run_id` int, `problems == []`, `notices` list,
  `n_new_listings` 2, 2 rows in `listings` and `alert_emails`. Same post again -> 2/0/2/0/0, larger `run_id`,
  `n_new_listings` 0, still 2 rows.
- `..._rejected_email_is_a_problem_not_an_error`: the 2021 fixture -> 200 (not 400), 1/0/0/1/0, one problem
  `rejected` with `alert_date` starting 2021-03-10.
- `..._run_kind_is_file_ui`: `GET /api/runs/{id}` of an import has `kind == "file_ui"` (data-model).
- `..._malformed_body_is_400` (8 params: no `files`, `files` string/object, item without content / without name,
  invalid base64, item a string, `content_base64` an int), `..._body_not_json_is_400`: 400 each.
  `..._malformed_creates_no_run`: 400 and no `import_runs` / `alert_emails` rows.
- `test_api_runs_list_newest_first_and_limit`: 3 imports (OK_A, OK_A, OK_B); `GET /api/runs` ids descending, counts
  1/1/0/0/0, 1/0/1/0/0, 1/1/0/0/0 newest first; `?limit=2` gives the two newest.
- `test_api_runs_get_one_with_problems`: import OK_A + 2021 -> `GET /api/runs/{id}` has `run_id`, counts 2/1/0/1/0,
  one `rejected` problem (2021 date), `notices` list.
- `test_api_runs_unknown_id_is_404`: real run id -> 200, id+1000 -> 404.

## Notes for the developer
- Windows: `no_network` patches `socket.connect`, which asyncio's self-pipe needs when the TestClient portal
  creates its event loop. The `client` fixture therefore enters `TestClient` as a context manager and tests list
  `client` BEFORE `no_network` in their arguments (keep that order). No conftest change needed.
- `GET /api/runs` returns a JSON list of summary objects (assumed from "?limit=20"); each has `run_id`, `kind`,
  `n_*`, `problems`? (only asserted on the single-run endpoint).

## Contract gaps (not asserted)
- Which status for an unreadable name/extension (`a.msg`, no extension) in a well-formed body: not asserted; T018
  counts these as `failed` problems inside a 200 run, which seems the natural fit ("400 only for malformed").
- Empty `files: []`: not asserted (400 or 200 with 0 found both defensible).
- Whether problems/notices are persisted for old runs (`notes` column holds notices; problems would need to be
  derived from `alert_emails`): test only requires `GET /api/runs/{id}` right after import to include them, as
  api.md says. Whether `GET /api/runs` list items carry `problems`: unspecified, not asserted.
- Default `limit`, invalid `limit` (non-integer / 0): unspecified, not asserted.
- `kind == "file_ui"` comes from data-model, not api.md; if T020 chooses otherwise this is a spec question.
- Duplicate file names inside one request, size limits: unspecified.
