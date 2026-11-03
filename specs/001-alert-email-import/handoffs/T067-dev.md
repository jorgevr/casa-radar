# T067 / T068 dev handoff: availability (gone / relisted)

Result: `tests/test_availability.py` 18 passed (was 16 failed). Full `-m "not slow"`: 218 passed.

## Changes
- `app/main.py` (T067): `PATCH /api/listings/{id}` accepts `availability`. Anything but the strings `active` or `gone`
  (null, "", `GONE`, numbers, lists) gives 400 before any field is written. A valid value sets `availability` and
  `availability_changed_at = db.today()` on BOTH changes (user decision in T066 handoff), then calls
  `derive.derive_listing` so the stored relisted flag is refreshed against the new mark (e.g. back to `active` drops it).
  Commit is the existing single `conn.commit()`.
- `app/scoring.py` (T067): `rank()` inserts `ya no disponible` first in `eval.flags` for `availability == 'gone'`; sort key
  is now `(excluded, gone, -score)`: gone listings go after active ones inside each of the excluded / non-excluded groups,
  and are never excluded by this. Stored `alert_flags` (incl. the relisted flag) were already merged into `eval.flags`.
- `app/derive.py` (T068): never writes `availability`. When the stored listing is `gone` with a date, flag
  `vuelto a ver en una alerta el <dd/mm/aaaa>` is appended to `alert_flags` if any sighting's local day (`seen_at[:10]`,
  the alert's own date) is strictly after `availability_changed_at[:10]`; the date shown is the latest such day.
  It is computed from all sightings plus the stored user-owned mark on every derivation, so it is order independent
  and rebuilt each time (never carried over from the previous flags).
- `app/db.py` untouched (columns already exist). `app/static/index.html` untouched.

## Decisions
- SCORING_VERSION stays 2, no bump. Article VIII bumps it when scoring logic changes the results; here no score or
  component value changes, only a flag and the display order of already-computed results, and research R14 / data-model
  fix the version at 2 (a test in `tests/test_api_sorting.py` pins the literal 2 in the CSV). A bump would break that
  test, so per instructions I did not do it. If the reviewer reads the sort as a scoring change, the bump needs a user
  decision plus a test update.
- Equal day: a sighting on the same local day as the mark is NOT relisted (it may predate the mark; the date has no time).
  Only a later day triggers the flag.
- The PATCH re-derivation only touches listings that have sightings; manual listings are unaffected (derive returns early).

## Reviewer should check
- The re-derive call in PATCH does not alter other derived values for an already-derived listing (full suite green).
- Placement of `ya no disponible` at the front of the flags; the sort key for gone listings among excluded ones.
- Gates: compileall clean; anonymise check exit 0; diff vs `jorgevr/spec-kit-3-feature` shows only specs/tests/app files
  of this task, requirements.txt unchanged.
