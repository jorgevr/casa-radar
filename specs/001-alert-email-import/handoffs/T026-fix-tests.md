# T026-fix-tests: regression tests for review findings 1-3

File: tests/test_derive_protection.py (new; T022/T023 files, app/ and conftest.py untouched).

## Tests, assertions, why they fail now
1. test_sighting_without_link_or_matching_location_keeps_known_identity_fields (FR-011): an `idealista` listing
   with known url/title/municipality/district/zone_id, then a sighting with no link_direct and an unmatched
   location. Asserts the five columns are unchanged. Fails: url is None (derive writes rows[-1]["link_direct"] unconditionally).
2. test_sighting_without_type_or_location_text_does_not_null_the_title: title stays "Piso en Getafe". Fails: title becomes None.
3. test_alert_prices_do_not_touch_a_user_owned_price[manual|csv] (FR-007/023/036): price 700.000, alerts 645.000 (26 Oct)
   and drop 645.000 -> 630.000 (28 Oct). Asserts price 700.000, price_updated_at None, and price_history identical
   to the user's rows (no alert/alert_previous rows). Fails: price_updated_at == '2026-10-28'. The history
   assertions are after it and are reached only once that is fixed.
4. test_area_from_idealista_api_keeps_its_origin_when_alerts_do_not_state_it: field_sources.area_m2 stays
   'idealista_api'. Fails: relabelled 'alert'.
5. test_area_stated_by_an_alert_on_an_alert_listing_is_labelled_alert: passes now (guard against over-fixing).

## Ambiguity
data-model says alert history rows are rebuilt "for alert listings"; it does not say what happens to a listing
whose price is user-owned. I read that as: no alert rows, and assert the history equals the user's rows exactly.
If the coordinator prefers keeping alert rows as pure history, relax only the last two assertions of test 3
(price and price_updated_at assertions stand either way per FR-007/FR-036).

## Gates
compileall OK; existing suite 132 passed (not slow) with the new file deselected; new file: 5 failed, 1 passed.
