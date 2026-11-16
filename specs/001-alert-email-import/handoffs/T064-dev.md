# T064 — Article VIII end to end (dev)

**Result: verified, no defect found, no app/ changes.**

## Existing coverage found
- CSV `scoring_version` column and value `2`: `tests/test_api_sorting.py::test_export_csv_scoring_version_and_found_via`, `tests/test_api_units.py` guard.
- Gaps: no test ran the ranking twice; no test asserted per-listing `scoring_version` in `/api/listings`
  (test_api_sorting only notes it as "T032").

## Added: `tests/test_article_viii.py` (only new file)
Seeds a temp db by importing 4 anonymised fixtures via `POST /api/alerts/import`, with the example needs file.
- `test_ranking_twice_is_identical`: two `GET /api/listings` -> equal JSON and equal raw text (key order too); nothing ignored.
- `test_csv_export_twice_is_identical`: two `GET /api/export.csv` -> equal text.
- `test_scoring_version_on_every_listing_and_csv_row`: every listing item has `scoring_version == 2`; CSV has the
  `scoring_version` column, `"2"` on every row. Expected 2 is research R14's literal (contracts/api.md), not imported from app.

## Evidence
No clock/randomness difference between runs: both runs byte-identical. The tests passed on first run
(verification of existing behaviour, so there was no red phase). Contract wording: `/api/listings` "gains scoring_version";
implemented per item (`app/scoring.py` sets `l["scoring_version"]`), the response stays a plain list.

## Reviewer check
Gates and diff-scope results are in the commit/report. Fixtures are real anonymised emails; test is offline (`no_network`).
