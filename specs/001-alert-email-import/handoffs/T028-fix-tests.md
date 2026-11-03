# T028 fix-loop: test author handoff

New file only: `tests/test_scoring_ranking_inputs.py` (no change to app/, conftest, or existing tests).
Run: 21 tests, 14 pass now (behaviour already correct), 7 fail (behaviour missing). Existing suite unaffected (118 passed).

## Tests, hand calculations, status
1. History order (3 tests, all PASS now; the dev's SQL is right, they pin it):
   - same day, `alert` row inserted first (lower rowid), `alert_previous` 670000 second: required order 670000 -> 645000.
     drop = 1 - 645000/670000 = 25000/670000 = 0.0373134 -> flag text `bajada de precio acumulada 3.7%`
     (scorer formats `{drop:.1%}`, no space before %), momentum = clamp(0.0373134/0.10) = 0.373134.
     Wrong (rowid) order would give 645000 -> 670000: drop = -0.0388, no flag, momentum 0.
   - same with opposite insertion order (same values).
   - day beats origin/rowid: 700000 (05-01) -> 630000 (05-02): drop = 70000/700000 = 0.10 -> "10.0%", momentum 1.0.
2. alert_flags (8 tests, PASS now): stored list appended after existing flags, stored order, repeats and a text equal
   to an existing flag not duplicated; None, '', invalid JSON, JSON object, JSON string, number, null -> flags unchanged.
3. merged_into: hidden + `merged_links == [url]` + empty list (PASS now). CHAIN test FAILS: A->B, B->C gives
   C.merged_links == [B url], A's url is lost; expected both (any order, test sorts).
4. Medians (3 tests, all FAIL now: merged listing still feeds build_context):
   - min_listings_for_median=3, visible 4000/5000/6000 EUR/m2 + merged 10000: expected benchmark 5000
     (median of 3); code gives 5500 (median of 4). discount 1 - 4000/5000 = 0.2.
   - 2 visible + 1 merged with min 3: expected no benchmark (None, price component None, flag
     "sin referencia de precio para esta zona"); code gives 4500.
   - zone_table, min 2: visible 4000, 5000 -> n=2, median 4500; code gives n=3 (median 5000).
5. Unknown type (3 parametrized cases None, '', 'otro': FAIL now, flagged "posible duplicado de B"); known-type
   control 'piso' passes.

## Ambiguities / notes
- Test 5 asserts 'otro' is unknown even when both are 'otro'. Fix can be done either in duplicate_pairs (skip
  None/''/'otro') or by treating those as unknown; test only checks the outcome.
- Test 4 assumes `build_context` is where merged rows must be excluded (it feeds both rank and zone_table), and that
  merged rows are excluded from both medians and counts. A fix that resolves merge chains for merged_links must
  walk to the final target; a cycle (A->B->A) is not tested.
- Fix 3 may need the 'otro' tests' flag text unchanged; no test about days_seen or SCORING_VERSION.
- The weak last assertion in the first history test (`price_drop > 0`) only restates the hand calc.
