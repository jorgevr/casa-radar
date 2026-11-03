# T025 tests handoff

File: `tests/test_api_sorting.py` (only file added besides this handoff). Nothing under `app/` and no `conftest.py` change.

## Scope decision (user, supersedes the shorter T025 text)
- `GET /api/listings` stays a list; each listing gains `published_at` and `price_updated_at`. No top-level `scoring_version` (per-listing `scoring_version` is T032, Phase 5).
- `GET /api/export.csv` header gains `published_at`, `price_updated_at`, `found_via`, `scoring_version`.
- `scoring_version` constant `SCORING_VERSION = 2` is introduced by T028 (research R14); the test uses the literal `"2"`, not an import.
- Columns/keys are written by T029 (`app/main.py`); `price_updated_at` must also be derived (today `app/derive.py` only sets `published_at`).
- `found_via` is the empty string for every fixture listing in Phase 4 (unknown, Article I); the assertion changes in Phase 5 (T034).

## Fixture data (all imported via POST /api/alerts/import, hand-read from Date headers and alert types)
| listing | alert | published_at | price_updated_at |
|---|---|---|---|
| 112882173 | new listing, 22 Oct 2026 | 2026-10-22 | null |
| 112887282 | new listing, 23 Oct 2026 | 2026-10-23 | null |
| 112658090 | price drop, 23 Oct 2026 | null | 2026-10-23 |
| 112842548 | price drop (Torrejon), 26 Oct 2026 | null | 2026-10-26 (tasks.md Phase 4 test) |

## Tests
1. `test_listings_return_published_and_updated_dates`: response is a list; the four ids exist; both keys present per listing; values as in the table. Fails now: `price_updated_at` is None for 112658090 (key exists in the DB row but derive does not compute it).
2. `test_export_csv_has_the_new_columns`: header has the four columns, one row per listing, rows as wide as the header. Fails now: `published_at` not in header.
3. `test_export_csv_scoring_version_and_found_via`: every row `scoring_version == "2"` (R14), `found_via == ""` (changes in T034). Fails now: `scoring_version` not in header.
4. `test_export_csv_dates_match_the_listings_and_null_is_empty`: row found by `/<code>/` in the `url` column; date cells equal the table, empty string when null. Fails now: `published_at` not in header.

## Reviewer notes
- Row lookup relies on the `url` column holding the direct link `.../inmueble/<code>/` (true in the fixtures; the CSV has no id column).
- Dates are the alert's local date (Date header as written), consistent with `derive._day`.
- Gates run: compileall OK; existing suite 106 passed (not slow) with this file excluded; new file 4 failed for the reasons above.
