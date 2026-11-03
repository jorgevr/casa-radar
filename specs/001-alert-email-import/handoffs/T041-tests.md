# T041 tests handoff

File: `tests/test_api_units.py` (tests only, no app code). Run once: 22 failed, 1 passed (the guard).
Failures are behaviour gaps: PATCH ignores `price`/`area_m2`/`bedrooms` and returns 200 with nothing stored.

## What the tests assert
- PATCH `price` 417000, `area_m2` 131.5, `bedrooms` 4 (hand-picked, differ from the alert) each: 200, value on the listing, `field_sources[field] == "manual"`; also all three in one body.
- Protection: after a PATCH, toggling `availability` gone/active (which re-derives from the stored alert sightings) leaves value and `manual` origin unchanged.
- Rejected with 400 and the listing unchanged (whole `GET` row equal before/after): price -1, 0, "abc", true, false; area_m2 -50, 0, "abc", true; bedrooms -1, "abc", true, false, 2.5. A mixed body (valid price + invalid area) is atomic: 400, nothing changed.
- Export: `scoring_version` already exists in `/api/export.csv` (T029; tests in `tests/test_api_sorting.py`). Only a guard test added; no new app work needed for that part.

## Decisions the docs do not cover (reviewer / dev please check)
- Null: not tested. The only existing null convention is `new_build` (null drops the source). For units, clearing would erase a stored value or need a fallback; contract is silent. Dev must pick (suggest 400) and say so.
- `bedrooms: 0` (studio) is NOT in the rejected list, deviating from "zero rejected": zero bedrooms is a legitimate value. Not asserted either way. Fractional bedrooms (2.5) are rejected.
- Numeric strings such as "300000" are not tested.
- Re-derivation is exercised via the availability PATCH, not by importing a second alert, because the same alert file would be skipped as a duplicate.

## Addendum: overflow and atomicity (review T040 finding 1)
Added to `tests/test_api_units.py` (uses a client with `raise_server_exceptions=False`, so a 500 shows as a status, not an exception).
- Out-of-range values give 400 and leave the listing unchanged: integers 2**63, -(2**63)-1 and 10**30 for price, area_m2 and bedrooms; floats 1e308 and 1e12 for price and area_m2.
- Atomicity: `{"notes":"X","status":"shortlist", <invalid unit>}` (price 10**30, area_m2 1e308, bedrooms 2**63, price -1) gives 400; the row is identical afterwards, and still identical after a following valid PATCH (availability) that commits.
- Assumed bounds (the dev may choose tighter, but these must be rejected): integers must fit SQLite's signed 64-bit range; price and area_m2 must be strictly below 1e12 (1e12 itself is rejected). Bedrooms has no extra cap beyond int64.
- Checked: on this branch the 16 new tests fail (200, units ignored). Against the dev branch (7fb6907, scratch copy outside the repo, nothing committed there) they also fail: 500 for the huge integers, 200 for the others.
