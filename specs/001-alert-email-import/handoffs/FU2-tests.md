# FU2 tests handoff

File: tests/test_followups_merge_rank.py (only file added). Run result now: 9 failed, 4 passed.

## Failing (right reason)
1. Merge history (4 tests): merge only does `UPDATE listings SET merged_into`; it does NOT move or combine
   price_history rows, and GET price-history returns `WHERE listing_id=?` only. So the survivor shows only its
   own rows. Tests assert the combined list (day, alert_previous first, rowid), legacy NULL-origin rows kept,
   chained merge a->b->c gathers all on c, and no stored rows lost (count does not drop; survivor shows both).
   Tie order on the same day and origin is by rowid across both listings (src rows inserted before dst rows by
   construction; holds for read-time union ordered by rowid or for moving rows). Existing test
   test_merged_listing_still_answers_for_its_own_id (merged id answers its own rows, target "not combined")
   will contradict FR-018 combined history for the TARGET and must be revisited by the dev: the dst assertion
   there (`# the target's own history, not combined`) conflicts. Flagging for the coordinator; I did not edit it.
2. rank() duplicates (5 failing parametrized/other): `duplicates: None` and `{}` already work; a null SUB-value
   (`{"area_pct_max": None}`) overrides the default and raises TypeError at scoring.py:275-276. Fix: drop None
   values before merging with DUPLICATE_DEFAULTS.

## Passing already (kept as regression guards)
4. PUT /api/categories unwritable: main.py already catches OSError -> 500 with a path-free message. Two tests
   (directory as rules path; save_rules raising PermissionError with the path) pass and assert JSON body,
   no path/dir name leaked, and original file bytes unchanged.

## Not added
3. Merge double-submit: the second identical POST currently returns 200 (idempotent re-set of the same
   merged_into, data unchanged); contracts/api.md defines no 404/409 for it, so there is no failing test.
   If the dev wants a 409 for "already merged", that is a contract change to decide.

## Decisions
- Identical day+price+origin rows from both listings are NOT required to be deduplicated; tests use distinct rows.
- Seeding uses sightings + derive.derive_listing, hand-written expected rows (comments show the calculation).
