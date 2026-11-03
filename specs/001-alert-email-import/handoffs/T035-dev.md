# T035 dev handoff

Files: `app/main.py`, `app/cli.py`, `app/categories.py` (small, see below). No db.py/scoring.py/derive.py/alerts.py/index.html/tests touched.

## Changes
- `GET /api/categories` -> `{rules, search_names:[{name, category, emails}]}`. search_names = stored emails grouped by search name
  (null/empty names skipped), `category` is the stored email category (MIN over the group; unknown if null), `emails` the count, ordered by name.
  A malformed existing rules file -> 500 JSON `{"detail": "alert category rules unreadable: <ValueError text>"}`, no traceback.
- `PUT /api/categories` body `{"rules": [...]}` (as the tests send it). Validated with the same checks as `load_rules`
  (`categories.validate_rules`, extracted from `load_rules`); 400 + clear message and nothing saved on bad input. Then atomic save, then
  `recategorise_all` (FR-031). Returns the same view as GET.
- `PATCH /api/listings/{id}` `new_build`: true/false -> `(1|0,'user')`; null -> `(NULL,NULL)` then `derive_listing` (email statement
  brings back `(1,'email')`); anything else (1, 0, "yes", [] ...) -> 400 before any write. Validated before every other write so a bad
  request changes nothing. Existing fields and availability handling unchanged.
- `python -m app.cli categories`: read-only; prints rules, then each stored search name with its category (computed now with the current
  rules) and email count. Malformed file -> message on stderr, exit 1.
- `app/categories.py` (strictly needed): `validate_rules(data, where)` extracted from `load_rules` (same messages); `save_rules` now
  atomic (temp file next to the target + `os.replace`, temp removed on failure).

## Decisions the docs do not cover
- PUT body shape `{"rules": [...]}` (contract shows `rules` key); a bare list is a 400.
- Malformed existing file on GET/PUT-recategorise is a 500 (server-side config problem) with a JSON message.
- Validation of the PATCH body is done up front, so a bad `new_build` with a valid `status` writes nothing.
- CLI category is recomputed from current rules, not read from the stored email column.

## Reviewer
- `put_categories`: if `recategorise_all` fails after the save, rules stay saved (it only fails on a malformed file, which was validated).
- `categories_view` uses stored categories; CLI recomputes. They agree after any PUT/import.
- Gates: compileall OK; pytest -m "not slow" 307 passed (incl. 24 API tests); anonymise check rc=0; forbidden-path diff only lists
  `tests/test_categories_api.py`; requirements.txt diff empty; CLI tried under CASA_* temp env (empty DB, tracked rules listed).

## Fix loop 1 (review T035-r1)
- app/main.py only; derive.py NOT touched (setting the label in PATCH is enough: derive's nb_owned keeps (v,'user') and its labelling loop leaves 'manual').
- PATCH `new_build` true/false: also sets `field_sources['new_build']='manual'` (other keys untouched), whether or not an email stated it. null: removes that key and clears the value, then `derive_listing` re-derives (email statement -> (1,'email') labelled 'alert'; none -> null, no key).
- Non-blocking note done: `PUT /api/categories` returns a JSON 500 ("rules file could not be written (<ErrorName>); nothing was saved", no path) when the save raises OSError (read-only/locked file). Not covered by a test.
- Gates: compileall OK; pytest -m "not slow" 319 passed; anonymise rc=0; forbidden-path diff clean; requirements.txt and config/alert_categories.yaml unchanged.
