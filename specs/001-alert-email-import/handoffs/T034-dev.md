# T034 dev handoff

Files: `app/alerts.py`, `app/derive.py`, `app/scoring.py` (+ `app/categories.py` from T033). No db.py/main.py/cli.py/index.html/tests touched. `SCORING_VERSION` stays 2 (user decision).

## Changes
- alerts.py: on storing any email, `category` and `category_rules_matched` (JSON) come from `categories.categorise(search_name or subject)`; the sighting copies the category.
- derive.py: `listings.categories` = JSON list of the distinct sighting categories, alphabetical (a sighting with null category counts as `unknown`). new_build: any sighting states it -> (1,'email'); else any sighting category `new-build` -> (1,'category'); a `user` origin is never changed; any other stored non-null value (API/csv/manual) is kept; a stored `category` value is re-derived (so changed rules can remove it). Category never touches property_type.
- scoring.py: flags `encontrado vía: <known categories, alphabetical>`, `encontrado vía: búsqueda desconocida` (when `unknown` is among the categories), `reglas de categoría en conflicto: <rules>` (rules of emails with category unknown and a non-empty rule list, file order, no repeats, joined with ', '), and `obra nueva según la categoría de la alerta, confirma` (new_build=1 with origin 'category'; emitted in `evaluate` just before the mortgage estimate, also when no estimate can be made). Cost estimate still uses `bool(l["new_build"])`.

## Decisions the docs do not cover
- Flag `la categoría dice obra nueva, el email dice segunda mano` is in derive's `alert_flags`; it can only fire when a sighting has `new_build_stated = 0` (the reader never writes 0 today). In that case the category does NOT set new_build (email wins).
- A listing seen under known and unknown categories gets both found-via flags.
- Found-via/conflict flags are computed in `rank()` (conflict rules via a join of sightings and alert_emails), not stored.
- No `field_sources` label for a category-set new_build.
- Legacy listings (categories NULL until re-derived) show no found-via flag.

## Checks
- Order independence: all 24 insertion orders of 4 sightings (categories flat/new-build/unknown/house, one stating new-build, differing prices) with derive after each insert gave 1 distinct listings row (incl. field_sources, alert_flags, categories).
- tests/test_categories.py + test_scoring_new_build.py: 26 pass. Full suite `-m "not slow" --ignore=tests/test_categories_api.py`: 251 passed. test_categories_api.py not run (T035).

## Reviewer
- derive.py new_build block (stored 'category' re-derived; other stored values kept).
- alerts.py now categorises failed/rejected emails too.

## Fix loop 1 (review T034-r1), app/categories.py only
- `load_rules` is strict: one ValueError naming the file path for a non-UTF-8 file, a YAML syntax error, a non-list top level; and for a bad entry its 1-based position and the problem (not a mapping, or `contains`/`category` missing, empty or not a string; typo'd keys fall under "missing"). Missing, empty, comment-only file and `[]` are still no rules. Valid files unchanged (rules returned as `{contains, category}`).
- `categorise(text, rules=None)`: optional pre-loaded rules; otherwise loads the file, so the ValueError surfaces.
- `recategorise_all` loads and validates rules once, before opening the transaction (DB untouched on error), and passes them to `categorise` for each email (was one file read per email; same behaviour).
- Note: `categorise` now loads the file even for empty text, so a malformed file raises there too.
- Gates: compileall OK; pytest -m "not slow" --ignore=tests/test_categories_api.py 282 passed; anonymise check rc=0; forbidden-path diff clean; requirements.txt diff empty.
