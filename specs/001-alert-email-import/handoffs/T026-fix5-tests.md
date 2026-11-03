# T026 fix loop 6 - tests

File: tests/test_derive_user_municipality_zone.py (new; no other file touched).

Defect: with a user-owned municipality (field_sources.municipality manual/csv) derivation keeps the user's
district and zone_id but labels field_sources.zone_id 'alert', depending on processing order (R11, Art. VIII).

Setup: user listing Getafe / Centro / price 500000 (zone_id "getafe"). Sighting A (20 Oct, "Getafe") and
B (27 Oct, "Torrejon de Ardoz"), both resolved by zones.match_zone from the seeded data.

- test_manual_municipality_zone_label_is_the_same_for_every_order / test_csv_..._: runs A,B and B,A with a
  derive after each insertion, A,B and B,A derived once, and A only. Asserts municipality/district/zone_id
  stay Getafe/Centro/getafe, field_sources municipality keeps its origin, zone_id and district are never
  'alert', and (for the two-sighting variants) the whole listings row and the whole field_sources are equal.
- test_control_alert_municipality_zone_is_still_labelled_alert: no user listing, only sighting A; zone_id
  and municipality are written and labelled 'alert'.

Result before the fix: manual and csv tests FAIL with `assert 'alert' != 'alert'` on
field_sources["zone_id"] (variant "A then B, derive after each"); control passes.
