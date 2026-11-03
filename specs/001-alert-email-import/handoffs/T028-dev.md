# T028 dev handoff

Files: `app/scoring.py`, `config/needs.example.yaml` (only other file touched; new `duplicates` section). Tests untouched.

## What changed
- `rank()` reads price history `ORDER BY day, (origin='alert_previous') DESC, rowid`.
- `duplicate_pairs(rows, needs)` (R15): same zone_id, property_type, bedrooms; `|a-b|/max(a,b)` <= area limit and <= price limit, inclusive.
  Skipped: development=1, null zone, null/zero area or price, null bedrooms. Merged listings take no part. One flag
  `posible duplicado de <id>` per partner, on both listings, partners sorted by id.
- Listings with `merged_into` set are not returned by `rank()`.
- `SCORING_VERSION = 2` module constant; NOT added to rank output (T032).
- `listings.alert_flags` (JSON list) parsed defensively (null/empty/invalid JSON/non-list/non-string items -> nothing) and
  appended to `eval.flags` after the existing flags and after the duplicate flags, stored order, no duplicates.

## Decisions not in the docs
- Config keys: `duplicates.area_pct_max: 0.03`, `duplicates.price_pct_max: 0.05` (fractions) in `needs.example.yaml`, comment cites R15.
  If absent from the user's needs, `DUPLICATE_DEFAULTS` in scoring.py (same values) applies; a partial section falls back per key.
- `merged_links`: each rank dict gets `merged_links`, a list of the merged listings' `url` strings (empty list when none), on the target.
  A merge target that is itself missing from the table simply yields no row. No other fields (id, source) were added.
- Null bedrooms are treated as unknown (no flag), consistent with Article I.
- Merged listings still count in `build_context` medians (unchanged behaviour, not touched).
- Flag order: eval flags, duplicate flags, alert_flags.

## For the reviewer
- `needs.example.yaml` line endings: file is CRLF; appended block should be CRLF too (git warns on LF normalisation only).
- Existing user `needs.yaml` files lack the `duplicates` section; the fallback covers them (no migration needed).
- No test covers alert_flags merging or alert_previous ordering here (T025/T066 tests are in other branches); I checked both
  by an ad-hoc script in the temp folder (not committed).
- The ad-hoc script briefly created the worktree's ignored `data/casa.db` (CASA_DB unset in that shell call, contained only
  synthetic rows); it was deleted immediately. No real data was touched.

## Fix loop 1 (review findings), app/scoring.py only
- Merge chains: `rank()` follows `merged_into` to the final target, so with A->B, B->C, C.merged_links has A's and B's urls.
  A cycle stops the walk; every cycle member is merged, so none is returned and nothing crashes.
  If the final target id does not exist, its links are simply not shown.
- `build_context` (hence `rank` and `zone_table`) reads only listings with `merged_into` null or empty: merged rows no longer
  feed medians, counts or the minimum-count threshold.
- Unknown property type (`UNKNOWN_TYPES` = None, '', 'otro') never gets a duplicate flag. Decision: 'otro' is treated as unknown
  because `norm_type` maps missing and unmapped text to it (review finding 3); a genuine "otro" is therefore also never flagged.
- All 139 non-slow tests pass, including the 21 new ones; no test edited.
