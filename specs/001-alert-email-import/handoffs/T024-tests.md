# T024 tests handoff

File: `tests/test_scoring_duplicates.py` (tests only; nothing under `app/`, `conftest.py` untouched).
Listings are inserted directly (`_put`), zones via `INSERT OR IGNORE INTO zones`; flows through `scoring.rank`.
Rule source: spec FR-018, research R15 (and R13 for developments). Metric `|a-b|/max(a,b)`, area <= 0.03, price <= 0.05, inclusive.

## Tests, assertions, hand calculations
Base listing A: piso, zone-a, 3 bedrooms, 100 m2, 400000 EUR.
- `test_duplicates_golden` - B = 97 m2, 380000 EUR. Area 3/100 = 0.03, price 20000/400000 = 0.05: both on the boundary,
  flagged. Asserts A has exactly `["posible duplicado de B"]` and B exactly `["posible duplicado de A"]`.
- `test_area_just_over_three_percent_not_flagged` - B area 96.99: 3.01/100 = 0.0301 > 0.03; no flag on either.
- `test_price_just_over_five_percent_not_flagged` - B price 379960: 20040/400000 = 0.0501 > 0.05; no flag.
- `test_identical_values_flagged` - 0 % differences, flagged both ways.
- `test_metric_is_relative_to_the_larger_value` - areas 97 vs 100: /max = 0.03 flagged (dividing by min would be 0.0309, not flagged).
- `test_unknown_area_or_price_not_flagged` - NULL area / NULL price: no flag (Article I).
- `test_unrecognised_zone_not_flagged` - both zone_id NULL: no flag (NULL must not equal NULL).
- `test_development_not_flagged` - one side development=1: no flag (R13/R15).
- `test_different_zone_type_or_bedrooms_not_flagged` (3 params: other zone, type atico, 2 bedrooms).
- `test_merged_listing_is_skipped_in_ranking` - B.merged_into='A': `rank` returns only A, and A has no duplicate flag.

## Why they fail now (run: 4 failed, 8 passed; full suite 114 passed otherwise, compileall clean)
The 4 failures are behavioural: no duplicate flag is produced (`[] != ['posible duplicado de B']`) in golden,
identical and metric tests; merged listing B is still returned by `rank` (`{'A','B'} != {'A'}`).
The 8 passing tests are the negative cases; they pass vacuously today (no flag exists) and guard T028 against over-flagging.

## Floating point
Boundaries are exact: `3/100 == 0.03`, `20000/400000 == 0.05` (verified in CPython), and `0.03*100 == 3.0`,
`0.05*400000 == 20000.0`, so both the ratio form and the multiplied form are safe. 96.99 gives 0.03010000000000005
and 379960 gives 0.0501: both well clear of the limit. Not float-fragile.

## Open questions / notes
1. R15 does not say where the 0.03 and 0.05 thresholds live. Articles II/VIII want config, but `needs.example.yaml` has no key
   and the tests never set one, so they rely on the defaults equalling R15. The developer must choose the key (and, if
   it is new config, SCORING_VERSION handling is already planned in R14). If a config key is added, tests would still hold
   with the example needs.
2. "Different listing codes or sources" (FR-018) is trivially satisfied (distinct ids); not tested separately.
3. Flag text is the exact string `posible duplicado de <id>` using the listing `id`; if two or more partners exist, the tests do
   not cover multiple flags or ordering (not specified in the docs).
4. T028's "show their links on the target" for merged listings is not covered here (no data shape defined for it).
