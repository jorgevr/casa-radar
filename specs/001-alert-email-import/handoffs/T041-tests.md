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
