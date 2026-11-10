# FU2 review 2

Reviewer: Tier A (scoring/derivation). Commit f2f5f81 over jorgevr/spec-kit-3-feature. Round-1 review kept as FU2-r1.md.

## Gates
- compileall: OK
- pytest -q -m "not slow": 332 passed, 1 deselected
- anonymise check: clean (exit 0)
- forbidden-path diff: only app/main.py, app/scoring.py, handoffs, reviews, 2 test files; none forbidden
- requirements.txt diff: empty

## Round-1 findings resolved
1. rank() untouched in behaviour: diffing rank() against jorgevr/spec-kit-3-feature, the only change is the price_history query
   becoming an f-string over HISTORY_ORDER = "day, (origin = 'alert_previous') DESC, rowid". The resulting SQL text is
   character-identical to the old one. Nothing else in rank() differs, so output is identical for all inputs.
2. SCORING_VERSION is still 2 (app/scoring.py:19), consistent with no scoring change.
3. Combined history is display-only: used only in the price-history route (main.py) via combined_history_ids; rank() does not call it.
4. merge_groups() now delegates to scoring.merge_targets(). Compared with the old loop: same input map, same walk (seen-set,
   stop at a non-merged id or at a repeat), same exclusion of cycle members (a walk ending on a node still in `into` is dropped).
   Chains resolve to the final target; cycles yield no target. Behaviour preserved. rank() keeps its own walk (merged_links), by design.
5. duplicate_pairs: None sub-values fall back to defaults; non-None values override as before. Only change in that function.
6. The single edited existing assertion (tests/test_price_history_route.py, dst branch) is justified by FR-018 (combined price
   history); the merged id's assertion is unchanged. No test weakened, none removed.

## Findings
- minor: rank() still has its own chain walk (merged_links), so two walks remain (merge_targets and rank). Divergence risk only; accepted.
- minor: identical rows from both listings are not deduplicated (documented; acceptable).

STATUS: PASS
