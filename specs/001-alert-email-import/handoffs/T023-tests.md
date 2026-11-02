# T023 tests: user-value protection in derivation

File: `tests/test_derive_user_values.py` (helpers inside the file; conftest and app untouched).
Run result before implementation: 11 failed, 2 passed (the 2 pass trivially, see below). Rest of the suite: 106 passed, no collection errors.

The user's listing and the alert share one id: the tests take the id returned by `csv_import.import_csv_text` / `upsert_listing` and insert sightings with that `listing_id`, then call `derive.derive_listing`.

| Test | Asserts | Fails now because |
|---|---|---|
| `test_upsert_records_field_sources_by_origin[manual/csv/idealista]` | price, area_m2, bedrooms are recorded in `field_sources` as `manual` / `csv` / `idealista_api` (source arg `idealista` maps to `idealista_api`); null fields (bathrooms, plot_m2, lat, lon) are absent from the map | `field_sources` never written (T027) |
| `test_csv_import_records_csv_origin` | `import_csv_text(source="csv")` gives `csv` for price and area_m2 | same |
| `test_alert_area_differs_from_csv_area_user_value_stays_and_is_flagged` | CSV area 142 + alert 150 (27 Oct 2026): area 142, price kept, `alert_flags == ["la alerta dice 150 m² (27/10/2026)"]`, sighting still holds 150, origin stays `csv` | area overwritten with 150, no flag (T026) |
| `test_rederiving_does_not_duplicate_the_flag` | deriving twice leaves exactly one flag (flags rebuilt) | flag missing |
| `test_alert_with_same_value_as_user_raises_no_flag` | equal alert value: value kept, no flag | passes now (guards against over-flagging) |
| `test_alert_fills_a_field_the_user_left_unknown` | protection is per field: CSV without area, alert area 150 is written, no flag | passes now (guard; stays valid after T026) |
| `test_manual_price_is_never_replaced_by_alert_price_and_differing_price_is_flagged` | manual 700.000, alert 645.000 on 26 Oct: price 700000, flag `la alerta dice 645.000 € (26/10/2026)`, origin `manual` | price replaced, no flag |
| `test_manual_price_survives_later_and_lower_alert_prices` | with a later price drop to 630.000 (28 Oct), price stays 700000 and flag `la alerta dice 630.000 € (28/10/2026)` is among the flags | price replaced |
| `test_csv_price_is_never_replaced_by_alert_price` | same as manual, origin `csv` | price replaced |
| `test_alert_without_values_never_nulls_user_values` | sighting with null price/area/bedrooms: 500000/142/3 kept, no flags | price becomes NULL (derive writes `rows[-1]["price"]`) |
| `test_later_alert_without_price_does_not_null_an_earlier_alert_price` | alert-only listing: later sighting without price keeps 560000 (area 175 already works) | price becomes NULL |

All expected values are hand-written from the spec scenarios (no golden money maths involved).

## Decisions and ambiguities for the Developer / reviewer

1. **Money format in the flag.** Flag Texts says only `la alerta dice <valor> (<fecha>)` and, in the intro, "money `645.000 €`". I chose `la alerta dice 645.000 € (26/10/2026)` (dot thousands, space, euro sign), and `150 m²` for area (no decimals when integral), as in the task's own example. Format of other fields (bedrooms etc.) is not specified, so not tested.
2. **Which alert price is flagged when several differ.** Docs do not say. Test 2 only requires the flag for the *current* alert price (latest sighting) to be present (`in`), not that it be the only one.
3. **`field_sources` value for the API provider.** Task says `idealista_api` by source; the provider calls `upsert_listing(..., "idealista", ...)`, so the test maps source `idealista` to `idealista_api`.
4. **CSV origin.** `app/main.py` and `app/cli.py` call the CSV import with the default `source="manual"`, so a CSV uploaded through them would be recorded `manual`, not `csv`. The test passes `source="csv"` explicitly. A reviewer/coordinator may want the CSV upload paths to pass `"csv"` (not covered by T023/T027; outside the files they name).
5. **Null price over known price from an alert** (last test): R11 says "price of the latest-dated sighting", FR-011 says never null over known; I followed FR-011 (known price stays).
6. `field_sources` only has non-null fields written by `upsert_listing`; `property_type` is not asserted because `normalise` defaults it to `otro`.
