# T035 fix loop 1: tests for the new_build user label

File: `tests/test_categories_new_build_label.py` (new; no existing test or app file touched). Reuses the fixtures of
`tests/test_categories_api.py` (imports them). Source: reviews/T035-r1.md finding 1.

Rule asserted: PATCH `new_build` true/false -> `field_sources.new_build == 'manual'` (USER_ORIGINS), never `'alert'`;
null drops the user label and derivation relabels honestly (`(1,'email')` + `'alert'`, or NULL and no key).

Listings: `idealista:112882173` (obra-nueva fixture, email states new-build) and the first chalet without a statement
(`_chalet`, 112842548 today). Expected values hand-written.

## Tests and result against current app (6 fail, 6 pass)
Failing, for the right reason (label 'alert' or missing 'new_build' key):
- `test_patch_over_email_statement_labels_manual[False-0]`, `[True-1]`: label stays 'alert'.
- `test_patch_true_without_prior_value_labels_manual`, `test_patch_false_without_prior_value_labels_manual`: no label.
- `test_user_label_survives_rederivation[stated]` ('alert' instead of 'manual'), `[chalet]` (KeyError, no label):
  after PATCH false, `derive_listing` again and `recategorise_all` keep (0,'user') and 'manual'.

Passing today (guards for the fix, not defects): `test_setup_stated_listing_is_email_labelled_alert`,
`test_clear_over_email_statement_relabels_alert` (accidentally right, label was never changed),
`test_clear_without_statement_drops_label`, `test_patch_leaves_other_field_sources_unchanged` x3 (true/false/null; no other key altered).

## Notes for dev
- Fix goes in app/main.py PATCH: set `field_sources.new_build='manual'` for true/false; on null remove that key before
  `derive_listing`, so derivation can label 'alert' again. derive.py may need nothing (`nb_owned` already keeps the value),
  but re-derivation currently only preserves whatever label PATCH wrote, so the PATCH write is what matters.
- Not re-tested: the 'la alerta dice sí (<fecha>)' flag (T026 tests). A category-derived (1,'category') clear case is not
  covered: no fixture gives a category-only new-build without an email statement.
