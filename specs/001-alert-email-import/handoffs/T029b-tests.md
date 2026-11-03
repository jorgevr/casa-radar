# T029b tests: GET /api/listings/{id}/price-history

File: `tests/test_price_history_route.py` (new; no existing file touched, `app/` untouched).

Data is built with sightings plus `derive.derive_listing` (pattern of `tests/test_derive_prices.py`); the app runs in a
`TestClient` on a temp DB file and a second autocommit connection seeds it (client fixture before `no_network`).
Expected rows are hand-written with the arithmetic in comments (Article VII).

Contract asserted: 200, JSON list of `{day, price, origin}` only (no `email_id`), ordered by day, then
`alert_previous` first, then rowid (data-model "ordered by day, then alert_previous first, then rowid").

| Test | Asserts |
|---|---|
| test_price_drop_history_in_order | new listing 670.000 on 2026-10-23, drop 670.000 -> 645.000 on 2026-10-26: rows (10-23, 670000, alert), (10-26, 670000, alert_previous), (10-26, 645000, alert); keys exactly day/price/origin |
| test_same_day_alert_previous_sorts_before_alert_for_a_drop_only_listing | only the drop seen: (10-26, 670000, alert_previous) before (10-26, 645000, alert) |
| test_legacy_rows_with_null_origin_are_included_and_ordered | derived 10-20 500000 alert, 10-26 pair 500000/480000; legacy null-origin rows inserted later (10-26 485000, 10-24 490000): 10-24 legacy sits between by day; on 10-26 order is alert_previous, alert, legacy (rowid) |
| test_listing_without_history_returns_empty_list | existing listing whose price_history rows are deleted: 200 and `[]` |
| test_unknown_listing_is_404_while_a_real_one_is_200 | same client: real id 200, then unknown id 404. Distinguishes a real 404 from a missing route (which also gives 404): the first assertion fails today |
| test_merged_listing_still_answers_for_its_own_id | merged_into set on 2006: its own id still 200 with its own rows; the target's rows are not combined (Article IX) |
| test_get_has_no_write_side_effects | GET twice gives equal non-empty bodies; dump of price_history, listings, sightings, alert_emails unchanged |

Decisions the docs do not cover (the reviewer/dev should confirm): the error body of the 404 is not asserted;
"merged target does not include the source's rows" is my reading of "answers for its own id"; ids contain a colon
(`idealista:2001`), so the route needs the `{lid:path}` style already used by the merge endpoint.

## Failure summary (before implementation)

All 7 fail on the first status assertion with `405 Method Not Allowed` (the path currently matches a non-GET listing
route), i.e. missing behaviour, not import or syntax errors. `python -m compileall -q app tests` passes;
`python -m pytest -q -m "not slow"`: 7 failed (only these), 200 passed.
