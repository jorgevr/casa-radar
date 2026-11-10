# T037 tests handoff

File: `tests/test_scoring_unknown.py` (only file added besides this handoff).

## What each test asserts
- `test_unknown_fields_golden`: with all six hard filters configured (min_area 90, min_bedrooms 4, require_garden,
  min_plot 200, max_price 500.000, allow_zones [zona-a]) a satisfying listing has `eval.excluded == []` and no
  unknown/zone flag; then, one at a time, null area/bedrooms/garden/plot/price gives exactly
  `superficie desconocida` / `habitaciones desconocidas` / `jardín desconocido` / `parcela desconocida` /
  `precio desconocido` in `eval.flags`, no other unknown flag, and no exclusion; a null-zone listing with
  location_text "Urbanización Los Pinos" gives `zona no reconocida: "Urbanización Los Pinos"` and no exclusion.
  Hand reasoning and sources (FR-012, FR-013, data-model Flag texts) are in the module docstring.
- `test_known_values_still_exclude` (passes now, must keep passing): known failing values still exclude exactly once
  and add no "desconocido" / "zona no reconocida" flag.
- `test_existing_core_tests_untouched`: `git diff <merge-base with jorgevr/spec-kit-3-feature> -- tests/test_core.py`
  is empty (skips if the ref is missing). Dev should also re-run `tests/test_core.py` as T037 says.

## Current result
1 failed (`test_unknown_fields_golden`: flag `superficie desconocida` missing), 2 passed. No import errors.

## Decisions the docs do not cover
- The `<texto>` of the zone flag is taken from `listings.location_text`.
- Flags are asserted in `eval["flags"]` (where `rank()` exposes them), exclusions in `eval["excluded"]`.
- Behaviour with empty `allow_zones` and a null zone is NOT specified by the docs and is not tested.
- Unknown `tipo` (also in the flag table) is out of T037's field list and not tested.

## Reviewer check
Garden null is stored as SQL NULL (the current code only excludes `garden == 0`).
