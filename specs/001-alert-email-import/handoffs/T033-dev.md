# T033 dev handoff

File: `app/categories.py` (new). No other file touched.

## What it does
- `CATEGORIES_PATH` (module attribute, default `config/alert_categories.yaml`, read at call time), `load_rules()`, `save_rules(rules)` (pyyaml, already in requirements).
- `categorise(text)` -> `(category, matched_rules)`: slug() substring match; matched rules are the `contains` texts as written, file order; no match or different categories -> `("unknown", ...)` (conflict lists all matched rules, no match lists none).
- `email_text(search_name, subject)`: search name, else subject (used by `recategorise_all` and, in T034, by alerts.py).
- `recategorise_all(conn)`: for every stored email sets `category` and `category_rules_matched` (JSON), copies the category to its sightings, then calls `derive.derive_listing` for each affected listing.

## Decisions not in the docs
- `recategorise_all` commits (`with conn:`), unlike `derive_listing`: it is a whole-database operation (PUT /api/categories, T035). Failure rolls back everything.
- All stored emails are recategorised, including failed/rejected ones (search_name may be null, then the subject is used).
- Rules with empty `contains`/`category` are ignored on load; a non-list YAML raises ValueError (T035 should validate bodies itself).

## State at this commit
tests/test_categories.py: 10 pass, 7 fail only because `derive` does not yet write `listings.categories`/`new_build` and scoring has no flags (T034).

## Reviewer
Check the slug match (`-` joined) cannot match across word boundaries wrongly (substring on slugs, as the tests require).
