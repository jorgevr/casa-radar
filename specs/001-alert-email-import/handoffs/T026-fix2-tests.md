# T026-fix2-tests (review round 2, findings 1-3)

New file only: `tests/test_derive_order_and_legacy.py`. No change to app/, conftest or existing tests.
Expected values are hand-derived, reasoning in comments.

## What each test asserts

- `test_url_and_zone_come_from_the_latest_sighting_that_states_them_in_either_order` (finding 1): A (23 Oct,
  link, "Getafe") and B (26 Oct, no link, unresolvable text). Orders AB and BA, each also derived twice, give
  identical rows: url = A's link, municipality Getafe, district null, zone_id getafe.
- `test_newest_sighting_without_type_or_location_keeps_title_from_latest_that_has_them`: adds N (28 Oct, price
  only). Four orders give the same row; title "Piso en Urbanizacion Inventada Sin Zona" (latest type and
  location text, from B), url and zone from A.
- `test_newest_sighting_without_type_keeps_type_from_an_earlier_one`: title "Piso en Getafe" in both orders.
- `test_legacy_listing_without_field_sources_takes_newer_title_and_url` (finding 2): listing INSERTed with
  field_sources NULL, sightings A and C (type "Atico", other link). After re-derive (twice): "Atico en Getafe",
  C's link, equal to a fresh database.
- `test_url_and_title_with_a_recorded_non_alert_origin_are_not_replaced[idealista_api|manual|csv]`: guard kept.
- `test_zone_trio_overwritten_by_an_alert_is_labelled_alert` (finding 3): API listing (Getafe/Centro), alert in
  Torrejon de Ardoz; field_sources municipality, zone_id and district are "alert".

## Results against current app/derive.py

- Fail for behaviour (not setup): the first three (url/zone None in order BA), legacy (title stays "Piso en
  Getafe"), zone trio (label stays `idealista_api`).
- Already pass: the three non-alert-origin guard cases.
- compileall OK; rest of the suite unaffected (only the 5 new tests fail).

## For the developer / reviewer

- Coordinator ruling: field_sources records only non-null fields. The zone-trio test asserts the 'alert'
  label for municipality and zone_id only; district (null in the alert) must not be labelled 'alert': absent
  if cleared, or kept with its original `idealista_api` label if the stored value is kept (FR-011).
- Fresh databases are built inline (`db.connect(":memory:")` + `seed_madrid_districts`), so the same test can
  derive two separate databases.
