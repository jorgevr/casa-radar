# T041b tests handoff

File: `tests/test_scoring_user_price_momentum.py` (tests only). One run: 2 failed, 9 passed.

## Important finding
Through the real flow (sightings, then PATCH price) the behaviour is ALREADY correct: `derive_listing` sets
`history = []` when the price is user-owned and `_write_price_history` deletes the alert/alert_previous rows, so
momentum is None. Those tests (PATCH on a development, ordinary listing, later alert + availability re-derive,
route, guards) pass now and are regression pins. The gap is in `rank()`: it reads every price_history row and
never looks at `field_sources.price`. The two failing tests seed that state directly (user-owned price plus stored
alert rows, e.g. rows left from before the price became the user's, or a path that does not re-derive; derive also
returns early when a listing has no sightings):
`test_rank_ignores_stored_alert_series_when_price_is_user_owned[manual|csv]` fail with momentum 1.0 (the old
25 % result) instead of None. The fix belongs in `app/scoring.py` (skip alert/alert_previous rows, or the whole
history, when `field_sources.price` in manual/csv).

## What each test asserts
- Series (hand-calculated in the docstring): 800.000 then drop to 600.000; old result 1 - 600/800 = 25 %,
  momentum clamp(2.5) = 1.0, flag "bajada de precio acumulada 25.0%".
- Development stated 600.000, PATCH price 450.000 + area 120 + bedrooms 4: momentum None, price_drop None, no flag.
- Later alert (30 Oct, 600.000 -> 580.000) then availability PATCH (re-derive): price stays 450.000, source
  `manual`, `price_updated_at` unchanged, momentum None, no alert rows.
- Ordinary (non-development) listing with PATCH price: same.
- Guards: alert-priced listing keeps 25 % / 1.0 / flag / 3 alert rows; PATCH of area+bedrooms only keeps momentum;
  rank() with price source `alert` or absent keeps the stored series; SCORING_VERSION == 2.

## Price-history route policy (decision)
FR-007 records price changes from emails "unless the current price was entered by the user"; FR-036's updated date
is that of the latest alert that changed the price; data-model rebuilds only alert/alert_previous rows from
sightings, and derive yields none for a user price. So the supported claim is: after a user price, the route
returns no row with origin alert or alert_previous. Tested through the real flow (passes now). Rows of other
origins (null, user entries) are not asserted: the docs do not say whether user-entered history is shown.
I did not test the route with directly seeded stale alert rows: the spec does not require the route to filter
them, and that would force a main.py change the dev may not need.

## Notes
- Re-derivation uses the availability PATCH (same as T041 tests); a second identical alert file would be skipped.
- Isolation env vars set under $env:TEMP\casa-agent\P6-T041b\; tests are offline (`no_network`).
