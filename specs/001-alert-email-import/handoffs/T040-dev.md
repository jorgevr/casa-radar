# T040 dev handoff (app/scoring.py)

Status: BLOCKED on one test that looks wrong (not edited). Everything else passes: 386 passed, 1 failed.

## Test that looks wrong
`tests/test_scoring_zones.py::test_zone_less_median_golden` inserts all six chalets with `bedrooms=3`, but
asserts `excluded == []` for A1-A3 using `config/needs.example.yaml`, where `min_bedrooms: 4`. Known values
still exclude (T037), so `3 hab < 4` is correct and the assertion fails with or without T040. Proof: a scratch
copy with bedrooms 4 (deleted, not committed) passes entirely, including medians, benchmark, flags and the
null-zone checks. Fix needed in the test: bedrooms 4 (or relax min_bedrooms in `zneeds`).

## What changed
- `_hard_filters(l, needs, unchosen=False)` now returns `(excluded, unknown_flags)`; null area, bedrooms,
  garden, plot, price give the data-model flag texts and no exclusion. `evaluate` merges the flags.
- Null zone: skipped in `build_context` medians/counts; flag `zona no reconocida: "<location_text>"`;
  `allow_zones` excludes only a known zone outside the list.
- Development (R13): `unit_unchosen(l)` = development and not all of price/area_m2/bedrooms in
  `derive.USER_ORIGINS`. Then price/affordability/momentum are None, flag `promoción: sin vivienda elegida`,
  area/bedrooms/max_price filters flag instead of excluding, excluded from medians and `duplicate_pairs`.
  Once all three are manual/csv it is scored and duplicate-checked as normal.
- `rank()` sets `scoring_version` (SCORING_VERSION stays 2) on each listing.

## Decisions the docs do not cover
- Zone flag is emitted for any null zone, whether or not `allow_zones` is set; empty text if location_text is null.
- For an unchosen development the generic flags "falta precio o superficie" and "completa ahorros..." are
  suppressed (only the development flag explains it). "precio desconocido" still applies if price is null.
- Filtered-for-flag text for a stated development price over `max_price` is the usual `precio > ...` string,
  placed in `flags`.
- `tipo desconocido` (in the flag table) is not implemented: property_type is never null (`otro` is its
  unknown value) and T037 lists no test for it. Existing `tipo otro fuera de tus tipos` exclusion unchanged.
- T039 note: the development needs a property_type to match a duplicate; not changed (test sets 'piso').
- `scoring.py` now imports `USER_ORIGINS` from `derive` (no cycle).
