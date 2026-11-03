# T022 tests: price rules of derivation

File: `tests/test_derive_prices.py` (new; nothing changed under `app/`, `conftest.py` or existing tests).
Helpers (`_sighting`, `_add`, `_fixture`, `_history`, `_flags`) live in the file. Expected values are by hand
from the dates/prices in each test and, for the real fixture `112842548`, from its text ("ha bajado de 670.000 a
645.000", Date 26 Oct 2026 12:28 +0100). Flags are read from `listings.alert_flags` (JSON list; null = empty).
Flag strings are exactly data-model § Flag texts (dd/mm/aaaa, `645.000 €` with a normal space).

Result now: 13 failed (9 tests, several parametrised); existing suite without this file: 106 passed.
`compileall` OK. Every failure is a missing behaviour (assertion), none is an import/fixture error.

## Tests
- `test_later_lower_price_updates_price_and_history` (in-order / newest-first): 500.000 on 20 Oct, 480.000 on 25 Oct
  -> one listing, price 480.000, published 20 Oct, price_updated_at 25 Oct, history two `alert` rows, no flags.
  Fails: `price_updated_at` is None (price and history already right).
- `test_reverse_chronological_processing_keeps_newest_price`: 27 Oct, 24 Oct, 21 Oct processed newest first ->
  price 450.000, updated 27 Oct, history in date order. Fails: `price_updated_at` None.
- `test_same_day_different_prices_keep_higher_and_flag` (2 orders): 510.000 at 09:00 and 500.000 at 18:00 same day
  -> price 510.000, flags == ["precios en conflicto el 24/10/2026"], history exactly one row (day, 510.000, alert).
  Fails: price is 500.000 (latest-by-time wins today).
- `test_price_drop_for_known_listing_updates_it` (2 orders): synthetic new-listing 670.000 on 23 Oct + real fixture
  drop 670->645 on 26 Oct -> one listing, 645.000, published 23 Oct, updated 26 Oct, no flag, history
  [23 Oct 670 alert, 26 Oct 670 alert_previous, 26 Oct 645 alert]. Fails: `price_updated_at` None.
- `test_price_drop_for_unknown_listing_creates_it`: fixture alone -> created ("new"), 645.000, published null,
  updated 26 Oct, no flags, history alert_previous 670 then alert 645, sighting keeps previous_price 670.000.
  Fails: `price_updated_at` None.
- `test_previous_price_mismatch_flag` (2 orders): recorded 700.000 (20 Oct), drop 670->645 (26 Oct) -> price 645.000,
  flags == ["la alerta dice precio anterior 670.000 €, registrado 700.000 €"], history 3 rows. Fails: no flag.
- `test_older_price_drop_than_newest_sighting_is_history_only` (2 orders): drop 680->650 on 23 Oct, new-listing 600.000
  on 28 Oct -> price 600.000, updated 28 Oct, published 28 Oct, history 680 prev, 650, 600. Fails: `price_updated_at` None.
- `test_order_independence_over_20_shuffles`: the 12 fixtures plus 7 synthetic sightings (known-then-drop, conflict,
  old drop, mismatch), shuffled 20 times (seed 22) into fresh in-memory DBs; full `listings` rows (minus
  `first_run_id`) and `price_history` (ordered without rowid) must equal the first run; the first run is also
  checked against hand values (14 listings, 112842548 = 645.000/23 Oct/26 Oct, conflict and mismatch flags). Fails now
  on those hand values (`price_updated_at` None), so it is not vacuous; the 20-way equality itself holds today.

## Ambiguities / decisions the docs do not fully settle (please confirm)
1. `price_updated_at` for a listing created by a price drop (no earlier sighting): asserted = drop date (26 Oct), from
   FR-035 ("sets the current price and the updated date"). R11 literal wording ("differs from the one before it")
   would give null. Test for the unknown listing relies on FR-035.
2. Same-day conflict history: asserted exactly ONE `alert` row for the day with the higher price (data-model: "one
   `alert` row per date"). The conflict test does not assert `price_updated_at`.
3. A price drop whose stated previous price equals the recorded one still gets an `alert_previous` row (data-model:
   "one `alert_previous` row per price drop"), and no flag.
4. Older-drop case: `price_updated_at` = 28 Oct (date of the newest sighting, which differs from the 650.000 before it).
5. Flags are compared as lists in exact order; each test has at most one flag.
