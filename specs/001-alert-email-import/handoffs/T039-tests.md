# T039 tests handoff: developments (R13, R15)

File: `tests/test_scoring_development.py::test_development_golden` (one test). Result now: 1 failed, failing
on the first component assertion (`affordability` is 0.0, computed from the stated 600000, instead of None):
missing behaviour, not an import error. It then also needs T040 (flags, no exclusion, duplicate skip) and
T041 (PATCH of price / area_m2 / bedrooms, origin `manual` in `field_sources`).

## What it asserts
Setup: app via `create_app` on a temp db; needs PUT with savings 200000, net income 4000, `max_price` 500000,
`home.property_types` []. Rows inserted through a second connection: development (price 600000, no area or
bedrooms, `development=1`), flat (440000, 118 m2, 4 beds), far flat (450000, 100 m2, 4 beds), all `piso`,
same zone.
1. Before PATCH: price kept 600000; components price, affordability, momentum None; flag
   `promoción: sin vivienda elegida`; `excluded == []` (600000 > max_price would otherwise exclude); no
   duplicate flag on it or on the flat.
2. `PATCH {price: 450000, area_m2: 120, bedrooms: 4}` returns 200; GET shows the values and
   `field_sources` price/area_m2/bedrooms = `manual`; development flag gone; not excluded; affordability
   component 0.4985 (abs 2e-3), loan 282400, monthly 1190.61; score not None; no "te faltan" flag.
3. Duplicates: development gets exactly `posible duplicado de flat-1` and the flat gets
   `posible duplicado de dev-1` (area 2/120 = 1.67 %, price 10000/450000 = 2.22 %); the far flat
   (|120-100|/120 = 16.7 %) gets none.
Hand calculation and formula sources are in the module docstring (annuity formula, 421.60 per 100000 cross
check, affordability formula from `scoring.evaluate`, rates from `needs.example.yaml`).

## Decisions the docs do not cover (reviewer please check)
- Data-model says `property_type` is null for developments, and `duplicate_pairs` skips unknown types, so a
  development whose price/area/bedrooms the user set could never match unless it has a type. The test gives
  the development `property_type='piso'` (same as the flat). If T040 should match with a null type, the docs
  need a rule (PATCH does not accept a type). Left for the user to decide.
- The test clears `home.property_types` so the type filter does not exclude; the min_area_m2 / min_bedrooms
  "flag instead of exclude" part is not exercised because the development has null area and bedrooms (T040
  null-field flags apply there); the max_price case is exercised (600000 > 500000).
- `new_build` is left null, so the second-hand rate (ITP 6 %) is used in the hand calculation.
- Momentum after the PATCH and the exact wording of the stress-test flag are not asserted.
