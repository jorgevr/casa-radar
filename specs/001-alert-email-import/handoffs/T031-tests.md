# T031 tests: alert categories (split in two files)

Files: `tests/test_categories.py` (green by T033 + T034), `tests/test_categories_api.py` (green by T035, after T033/T034).
No `app/` changes. Expected values are hand-written from the rules inside each test (Article VII).

## State now (all new tests error in setup, nothing else changed)
- 42 errors, 0 other failures: 225 passed. Cause of all 42: `ModuleNotFoundError: No module named 'app.categories'`
  (fixture imports it lazily, so there is no collection error). No typos hidden: I checked with a throwaway stub of
  `app/categories.py` (deleted, not committed): the unit tests then failed on missing behaviour only (stale category
  not re-derived, flags absent, new_build not set) and the API tests on 404 for `/api/categories` (+ `KeyError: 'rules'`
  from reading that 404 body), PATCH `new_build` ignored, non-boolean accepted. The `404 unknown listing` test already
  passes once the module exists (route exists); it is a regression guard.

## tests/test_categories.py (no HTTP)
categorise: ignores case and accents (rule `Ático DÚPLEX en Getafe` vs `ATICO duplex EN getafe`); substring of a full
subject and of a bare search name; no match -> `("unknown", [])`; empty rules, `""`, `None` -> unknown; two rules, different
categories -> `("unknown", [both rules in file order])`; same category twice -> that category, both listed; rules read at call time.
recategorise_all(conn) (stale category/`["stale"]` pre-set in emails and sightings): updates `alert_emails.category` and
`category_rules_matched`, copies to `sightings.category`, rewrites `listings.categories`; a second rule change re-derives
(conflict -> unknown); idempotent. Flags via `scoring.rank(...)["eval"]["flags"]`: `encontrado vía: flat, new-build`;
`encontrado vía: búsqueda desconocida`; `reglas de categoría en conflicto: viviendas, zona personalizada` (+ unknown flag);
single category -> `encontrado vía: house` and no unknown flag. FR-032: `property_type` of listings and sightings unchanged.
FR-033/data-model: category new-build with no email statement -> `new_build=1, new_build_origin='category'` and flag
`obra nueva según la categoría de la alerta, confirma`; unmatched listing stays (None, None); a user value (0, 'user') survives.

## tests/test_categories_api.py
GET `/api/categories` -> `rules` equal to the tracked file's three rules, `search_names` with `name`, `category`, `emails`
(counts 1/2/2/1 from the fixtures imported through POST `/api/alerts/import`). PUT saves rules (file in tmp_path is a YAML list
equal to the body), re-derives emails/sightings/listings with no re-import, `GET /api/listings` shows `categories` (list) and the
new `eval.flags`; conflicting rules -> unknown; `[]` valid -> all unknown; nine invalid bodies -> 400 and file + GET unchanged;
tracked `config/alert_categories.yaml` bytes untouched. PATCH `new_build` true/false -> `(1,'user')`/`(0,'user')`; null ->
`(None, None)`; null on a listing whose email states new-build -> `(1,'email')` (re-derivation); non-boolean (`"yes"`, 1, 0,
`"true"`, `[]`) -> 400 and unchanged; unknown id -> 404.

## Assumptions to confirm (docs do not fix them)
1. Rules path: module attribute `app.categories.CATEGORIES_PATH`, read at call time (as `zones.ALIASES_PATH`); tests monkeypatch it.
   File format = list of `{contains, category}` as in the tracked file. No `load_rules`/`save_rules` names are asserted.
2. `matched_rules` = the `contains` strings as written, in file order; stored as JSON list in `category_rules_matched`.
3. `listings.categories` JSON list is alphabetical (the unit data makes first-seen order agree, so either reading passes).
   Conflict flag joins rule texts with `, `; the same listing also gets the unknown flag (its category is `unknown`).
4. `GET /api/listings` returns `categories` as a list (parsed), per contracts; response may be a list or `{listings: [...]}`.
5. PATCH `new_build: null` sets `new_build` and `new_build_origin` to NULL then re-derives (email statement may return, 1/'email').
   The non-boolean 400 for 1/0 is my reading of "true|false|null".
6. The import response key is `n_imported`; search-name `emails` counts stored emails of that name.
7. Only `app/categories.py` import is lazy; test_categories_api's "email statement back in" test skips itself if no fixture states
   new-build (it ran, did not skip, in my check with the stub).
