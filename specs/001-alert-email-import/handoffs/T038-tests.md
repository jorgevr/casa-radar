# T038 tests handoff

File: `tests/test_scoring_zones.py::test_zone_less_median_golden` (only file added).

Asserts (6 chalets, 120 m2, `min_listings_for_median`=3, `allow_zones`=[zona-a]):
- `build_context` medians/counts have no key with a None zone; medians == {(zona-a, house): 3500}
  (hand-computed in the docstring: 3000, 3500, 4000 EUR/m2).
- zone-a listing A1: benchmark 3500, discount 1/7; no zone flag; not excluded.
- three null-zone listings: benchmark None, discount None, exactly one flag
  `zona no reconocida: "<location_text>"`, and `excluded` has no "zona fuera de tu lista" (flag, not exclude).

Current failure: `(None, "house")` is present in `ctx["medians"]` (null zones grouped), the right reason.

Decisions / review notes:
- Flag text taken from data-model.md flag table (FR-013). Test does not check the flag's position in the list.
- Test checks `eval.excluded` for the null-zone listings via absence of the "zona fuera de tu lista" text only,
  since other hard filters are not under test here.
- Null-zone listings are asserted to have no benchmark (no notary data, no zone median), so also no
  "sin referencia de precio" assertion is made either way.
- Ran only this test, once, with CASA_* pointing at %TEMP%\casa-agent\P6-T038.
