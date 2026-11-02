# T027 + T026 dev handoff

Commits: `T027: record field_sources in upsert_listing`, `T026: complete derive price rules`.
Files: `app/listings.py` (T027), `app/derive.py` (T026). No tests, conftest, db.py, scoring.py, main.py, cli.py touched.

## T027
`upsert_listing` writes `field_sources` (JSON, sorted keys): every non-null field of the write gets the origin of
`source` (`idealista` -> `idealista_api`; `manual`, `csv` as given). On update the existing map is merged: a field now
null loses its entry, except `lat`/`lon` (the UPDATE keeps the old value via COALESCE, so the origin stays).

## T026 (derive.py)
- Price rules computed from sightings alone (`_price_rules`): per day the price is the highest stated (tie rule, flag
  `precios en conflicto el <dd/mm/aaaa>`); current price = latest day with a non-null price, else the stored one (FR-011).
- History: one `alert` row per day whose price differs from the previous; `alert_previous` row per price drop (dated that day).
- Mismatch flag when a drop's previous price differs from the price of the latest earlier day (earlier days only,
  same-day sightings are not compared).
- `price_updated_at`: latest day whose price differs from the prior day's; a first-ever day that is a price drop counts
  (FR-035 / Phase 4 test).
- Protection: a column whose `field_sources` is `manual`/`csv` (and stored value non-null) is never written; a differing
  alert value (price: current alert price; others: latest non-null) adds `la alerta dice <valor> (<fecha>)`.
  Also kept as the user's when their origin is manual/csv: url, title, municipality (then district and zone_id too).
- Fields derivation writes get origin `alert` in `field_sources` (data-model lists it); user origins are never replaced.
- `alert_flags` JSON list rebuilt on every derivation (ensure_ascii False).

## Decisions the docs do not cover
- Value formats in flags: money `645.000 €`; area `150 m²` (decimal comma if fractional); booleans `sí`/`no`; others plain.
- Several differing alert values: only the latest per field is flagged.
- Flag order: conflict/mismatch flags (by day) first, then user-value flags (price, then ATTRIBUTES order).
- `price_updated_at` and history use the local alert date (`seen_at[:10]`), as before.

## Open questions from T022/T023 handoffs, as resolved
T022 1: drop-created listing -> updated = drop date. 2: one `alert` row for a conflict day (higher price). 3: drop with
matching previous price still gets `alert_previous`, no flag. 4: updated = 28 Oct. 5: flags in order, at most one per test.
T023 1: formats as chosen by tests. 2: latest alert price only. 3: `idealista_api`. 5: FR-011 wins over "latest sighting".
T023 4 (user decision): `app/main.py` / `app/cli.py` keep `import_csv_text(..., source="manual")`, so CSV uploads are
recorded `manual`, not `csv`; call sites intentionally unchanged.

## For the reviewer
- derive treats `sources.get(col)` with a null stored value as unprotected (alert fills it).
- The merge of `alert_flags` into ranking flags is T028 in scoring.py (not here).
- Gates: compileall OK; pytest -m "not slow": 132 passed; anonymise check no output/OK; diff names only app/listings.py,
  derive via this commit, handoffs, the two test files; requirements.txt diff empty.

## Fix loop 1 (review findings 1-3), app/derive.py only
1. FR-011: `url` and `title` fall back to the stored value when the alert gives null. The zone trio
   (municipality, district, zone_id) moves together: when the alert's location matches no zone, all three keep the stored values.
2. User-owned price (`field_sources.price` manual/csv, value non-null): `price_updated_at` keeps its stored value and no
   `alert`/`alert_previous` rows are written (existing alert rows are removed). The price flag still applies.
3. `field_sources`: `alert` is set only when the stored value equals what an alert stated (price, url, title, attributes);
   kept fallback values keep their origin.
Decision not in the docs (forced by test 1): `url` and `title` that are already known are NOT replaced by the alert unless
their recorded origin is `alert` (so an API/user title survives an alert; alert-created titles still follow later alerts).
Consequence: listings whose title was written by derivation before this fix have no `title` origin and are now frozen.
Gates: compileall OK; pytest -m "not slow" 138 passed; anonymise check rc=0; forbidden-path diff clean; requirements.txt diff empty.

## Fix loop 3 (review round 2), app/derive.py only
1. Order independence: url = latest non-null `link_direct`; title from the latest type/location text; municipality/district/zone_id
   from the latest location text that resolves a zone. The stored row is a fallback only when no sighting supplies a value.
2. Legacy rows: a stored url/title is kept only when its `field_sources` origin is a known non-alert source (manual, csv,
   idealista_api). Origin missing or `alert` -> overwritten from sightings. The zone trio is still protected only for manual/csv.
   This supersedes the fix-loop-1 decision (frozen titles).
3. Labels: `alert` is set only for non-null values an alert wrote (zone trio included); a field written null loses its label
   (so a district cleared by an alert zone has no label). Kept values keep their origin.
Gates: compileall OK; pytest -m "not slow" 146 passed; anonymise rc=0; forbidden-path diff empty; requirements diff empty; no stray data/.
