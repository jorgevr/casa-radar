# T041b dev handoff

Files: `app/scoring.py` only (tests and main.py untouched).

Change: `rank()` loads listings first, computes the set of listings whose `field_sources.price` is in `USER_ORIGINS`
(new helper `_price_is_user_owned`), and skips `price_history` rows with origin `alert` / `alert_previous` for those
listings when building the momentum series. Other origins and non-user-priced listings behave as before.
SCORING_VERSION stays 2.

Decision: only alert-origin rows are skipped (not the whole history), since the docs do not say user-entered history
is excluded. The price-history route in main.py is not filtered (spec does not require it; derive already deletes
those rows in the real flow).

Gates: compileall OK; pytest -m "not slow" 414 passed; anonymise check no errors (no output); diff vs
jorgevr/spec-kit-3-feature lists only the T041b tests, tests handoff and this change; requirements.txt diff empty.
Reviewer: confirm skipping only alert rows (vs whole history) is the intended reading.
