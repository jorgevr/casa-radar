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
