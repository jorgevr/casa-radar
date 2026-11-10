# FU2 dev handoff

## REVIEWER: one existing test was edited (authorised exception)
`tests/test_price_history_route.py::test_merged_listing_still_answers_for_its_own_id`: only the target (dst)
assertion changed, from the target's own row only ("not combined") to the combined history
(21 Oct 400.000 + 22 Oct 410.000). The old assertion contradicted FR-018. The merged id's own assertion is unchanged.

## What changed
- `app/scoring.py`: `HISTORY_ORDER` (single definition of the price_history ORDER BY), `merge_targets(conn)`
  (id -> final live target, chains resolved, cycle members excluded), `combined_history_ids(conn, lid)`.
    `duplicate_pairs`: None sub-values of `duplicates` now fall back to defaults.
- `app/main.py`: price-history GET returns rows of the listing plus all listings merged into it (read-time union,
  nothing moved or deleted), ordered by `scoring.HISTORY_ORDER`. A merged id still answers its own rows only.
- Merge direction and double-merge behaviour untouched (second merge stays 200, idempotent).

## Checks
compileall OK; pytest -m "not slow": 332 passed; anonymise check clean; diff vs jorgevr/spec-kit-3-feature
(`jorgevr/spec-kit` is not a local ref) has no forbidden paths; requirements.txt diff empty.

## Reviewer notes
- `main.merge_groups()` still has its own chain walk; not changed (out of scope).
- Identical rows from both listings are not deduplicated.

## Review 1 fix
- `rank()` reverted to its prior behaviour (history keyed by the listing's own id; SCORING_VERSION stays 2). The only
  rank() diff vs jorgevr/spec-kit-3-feature is the query using the shared `HISTORY_ORDER` (identical SQL text).
- Combined history is display-only (price-history route).
- `main.merge_groups()` now builds on `scoring.merge_targets()` (one chain walk there). The separate walk inside
  `rank()` (merged_links) is left as is so rank() is untouched.
- Tests in tests/test_followups_merge_rank.py asserting that rank() uses combined history: none exist (the file
  tests the route and the duplicates fallback only), so no test needs fixing. Full suite: 332 passed.
