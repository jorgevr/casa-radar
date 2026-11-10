# FU2 review 1

Reviewer: Tier A (scoring/derivation). Commit e473117 over jorgevr/spec-kit-3-feature.

## Gates
- compileall: OK
- pytest -q -m "not slow": 332 passed
- anonymise check: no output / clean
- forbidden-path diff: only app/main.py, app/scoring.py, 2 handoffs, 2 test files; none forbidden
- requirements.txt diff: empty

## Verified OK
- Combined history on merge (app/scoring.py merge_targets/combined_history_ids, app/main.py price_history): read-time union,
  nothing moved or deleted. Chains a->b->c resolve to c; cycle members get no target, so they answer only their own rows.
  A merged id still answers its own rows only.
- Ordering of unmerged listings is unchanged: HISTORY_ORDER is the same ORDER BY string as before; groups for unmerged ids
  are their own rows only. SCORING_VERSION is still 2 (app/scoring.py:19).
- duplicate_pairs: None sub-values fall back to defaults (scoring.py:266); tests cover None, {}, single and double null.
- Golden hand calculations in tests/test_followups_merge_rank.py are written by hand with the arithmetic in comments; not read from code output.
- The one edited existing assertion (tests/test_price_history_route.py:154-155, dst branch) is justified by FR-018 ("combined price
  history"); the merged id's assertion is unchanged and nothing else was weakened.

## Findings

1. FAIL (major) - app/scoring.py:357-360 - the rank() change has no test. FU2 tests cover only the price-history route and
   duplicates. Nothing asserts that a survivor's momentum/"bajada de precio acumulada" in rank() uses the combined history
   once, or that nothing is double counted (e.g. src 720000 then dst 700000 and 660000). AGENTS.md and Article VII require golden
   tests with hand-calculated values for scoring changes, and tests come first. Scenario: a regression that groups by the
   listing's own id again (or counts rows twice) passes the whole suite.

2. FAIL (major) - app/scoring.py:19, 224-226, 357-360 - a scoring behaviour change without a SCORING_VERSION bump. For a
   merged survivor, `drop = 1 - history[-1]/history[0]` now spans two listings, so its momentum component, flags and score
   differ from before. AGENTS.md: "A scoring change bumps SCORING_VERSION". Either bump it (and say so in the handoff), or
   limit the change to the display route and leave rank() untouched. Note also that history[-1] may be the merged listing's
   row rather than the survivor's current price, and that cross-listing price differences (720000 vs 700000 on different
   listings) are read as a price "drop"; the dev handoff does not discuss this decision.

3. minor - app/main.py:47-60 merge_groups() and scoring.merge_targets() are now two chain walks (plus the one at
   scoring.py:364-375). Divergence risk only; the dev handoff flags it.

4. minor - identical rows from both listings are not deduplicated (documented; acceptable for FR-018).

STATUS: FAIL
