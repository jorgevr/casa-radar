# T066 tests handoff: availability (gone / relisted)

File: `tests/test_availability.py` (18 test cases). Implemented by T067 (`app/main.py`, `app/scoring.py`) and
T068 (`app/derive.py`). Result now: 16 failed, 2 passed; existing suite 106 passed; `compileall` clean.

## Setup / determinism
- Real fixtures only, via `POST /api/alerts/import`. Target listing `idealista:112887282` (one fixture, sighting
  2026-10-23). The id has a colon; requests use `/api/listings/idealista:112887282` (route `{lid:path}`).
- "Today" is controlled by monkeypatching `app.db.today` and `app.main.today` (raising=False, in case T067
  does `from .db import today`). Mark day = `2026-10-24`.
- Relisted sightings are synthetic: a copy of the listing's real sighting row with a new `email_id`
  (`synthetic-<tag>`) and `seen_at` 2026-10-25T10:00:00+02:00 (after the mark) or 2026-10-20 (before), plus a
  minimal `alert_emails` row, inserted through a separate `db.connect(file)` and re-derived with
  `app.derive.derive_listing`, then committed. No real mail, no network (`no_network`).
- Ranking numbers (hand-checked from a probe import, example needs): among 7 non-excluded listings,
  `idealista:112887282` and `idealista:112899473` score 50.0 (top); 4 listings are excluded by hard filters.

## Tests
1. `test_mark_gone_keeps_listing_with_flag_and_date`: PATCH gone -> 200; GET still returns it, availability
   `gone`, `availability_changed_at == "2026-10-24"`, `ya no disponible` in `eval.flags`, `eval.excluded == []`.
   Fails now: availability stays `active` (PATCH ignores the field).
2. `test_mark_gone_only_changes_that_listing`: the other 10 listings stay active, no date, no flag. Fails now:
   the target is not gone (this check was added so the test is not vacuous).
3. `test_mark_active_undoes_gone`: gone then active -> flag gone, still returned, changed_at = new today
   (2026-10-26). Fails: no availability handling.
4. `test_importing_fixtures_without_the_listing_never_changes_availability` (FR-019): mark, then import the 10
   other fixtures; target still gone, same date, flag present, 11 listings. Fails now only because the mark
   never happens.
5. `test_absence_does_not_mark_anything_gone_on_a_fresh_import`: guard, passes now and must keep passing.
6. `test_sighting_after_the_mark_keeps_gone_and_adds_relisted_flag`: baseline no relisted flag; after a sighting
   on 25/10 the listing stays gone, date unchanged, `vuelto a ver en una alerta el 25/10/2026` in `eval.flags`
   and in the stored `listings.alert_flags` JSON. Fails now: no gone state, no flag.
7. `test_sighting_before_the_mark_adds_no_relisted_flag`: sighting 2026-10-20 -> no relisted flag anywhere.
   Fails now only on the gone precondition.
8. `test_sighting_after_a_date_on_an_active_listing_adds_no_relisted_flag`: guard (flag only for gone); passes now.
9. `test_invalid_availability_is_400_and_changes_nothing` x8 (`banana`, `""`, `GONE`, `Active`, `null`, `true`,
   `1`, `["gone"]`): 400 and nothing changed. Fails now: returns 200.
10. `test_availability_does_not_break_other_patch_fields`: `{status: shortlist, availability: gone}` -> both applied.
    Fails: availability not applied.
11. `test_gone_listing_sorts_after_active_ones_without_being_excluded` (T067): before the mark the target is in
    the top two of 7 non-excluded; after it, 11 listings still returned, target `excluded == []`, last of the
    non-excluded, `idealista:112899473` first. Fails now: target is not last.

## Decisions / open questions for the reviewer
- Relisted flag is asserted in `eval.flags` (ranking flags; data-model says alert_flags are "shown with the
  ranking flags") and in the DB column `listings.alert_flags` (JSON list). If scoring does not yet merge
  `alert_flags` into `eval.flags` (the task that does so, T026 area, may not be merged), T067/T068 must.
- A `gone` listing must have `eval.excluded == []` (the mark is a flag + ordering, not a hard filter).
- Ordering is asserted only among non-excluded listings (gone after every active non-excluded one); where a
  gone listing sits relative to hard-filter-excluded ones is not specified, so not tested.
- `availability: null` and non-strings are treated as invalid (400); PATCH must also leave state unchanged.
- `availability_changed_at` is updated on every change including back to `active` (test 3); the docs only say
  "set to today" on the mark. Reviewer: confirm that is intended.
- Same-day sighting vs mark (date vs datetime comparison) is deliberately not tested (ambiguous in docs).
- Multiple later sightings: which date the flag shows (latest assumed) is not tested.
