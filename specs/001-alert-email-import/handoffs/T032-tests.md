# T032 tests handoff (test author)

File: `tests/test_scoring_new_build.py` (name as in tasks.md). No app/ change.

## Hand calculation (400.000 EUR)
Rates read from `config/needs.example.yaml` `costs:` (itp 0.06, ajd 0.0075, iva_new 0.10; the fixture asserts them).
`app/mortgage.py::purchase_costs`: new build taxes = price * (iva_new + ajd); second hand = price * itp.
- new build: 400.000 * 0.10 = 40.000 + 400.000 * 0.0075 = 3.000 -> 43.000
- second hand: 400.000 * 0.06 -> 24.000

## Keys read
`scoring.rank(conn, needs)[i]["eval"]["mortgage"]["taxes"]` (needs: example needs with `finance.savings` = 200.000 so the
estimate exists; example has savings null) and `["eval"]["flags"]` (flag text `obra nueva según la categoría de la alerta,
confirma`, exact from data-model Flag texts). Listing columns `new_build`, `new_build_origin`.
Data: sightings with explicit `category` (and `alert_emails.category`) written directly; listing built by `derive.derive_listing`.
The dev may emit the flag from derive (`alert_flags`) or scoring; either lands in `eval.flags`.

## Tests
- `test_new_build_from_category_golden` (a): /inmueble/ sighting, category new-build, new_build_stated null -> (1,'category'),
  taxes 43.000, flag present once. FAILS now (new_build stays null).
- `test_user_second_hand_replaces_category_value_and_costs` (b): after (a), user sets new_build=0/origin 'user' (simulating
  PATCH, which does not accept new_build yet: T035) + derive -> (0,'user'), taxes 24.000, flag absent. FAILS now (setup
  assertion: origin not 'category').
- (c) `test_stated_new_build_is_origin_email_without_category_flag`, `test_stated_new_build_wins_over_category`,
  `test_real_nueva_obra_nueva_fixture_is_origin_email` (real fixture 112882173, /obra-nueva/ link): origin 'email', no flag. PASS today.
- (d) `test_category_never_overrides_user_second_hand`: user 0 then a later new-build-category sighting -> stays (0,'user'),
  taxes 24.000, no flag. PASSES today (derive keeps user values); it guards the new category logic.
- (e) `test_other_category_never_sets_new_build[flat|house|None]`: (None, None), taxes 24.000 (unknown costed as second hand
  by `bool(None)`), no flag. PASS today.

## Notes
- Passing-today tests assert the absence of the flag, which holds vacuously until it exists; they matter after T034.
- The PATCH route is not used (T035 not merged); an API-level check of (b) belongs to T035's tests.
- Gates: compileall OK; pytest -m "not slow": 232 passed, 2 failed (the two tests above, for missing behaviour).
