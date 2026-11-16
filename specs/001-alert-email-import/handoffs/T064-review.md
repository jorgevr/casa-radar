# T064 — Review

**[PASS]** (two non-blocking notes)

## Scope
- `git diff --name-only 9d7863c` lists only `specs/001-alert-email-import/handoffs/T064-dev.md` and `tests/test_article_viii.py`. No `app/`, no `requirements.txt`, nothing under `data/`. Worktree clean. [PASS]

## (1) Runs twice, compares everything
- `tests/test_article_viii.py:46-47`: `first = imported.get("/api/listings")` / `second = imported.get("/api/listings")` on the same TestClient (same db + same needs file).
- `:51-52`: `assert first.json() == second.json()` and `assert first.text == second.text` — full output, no field filtered or ignored, key order included. Asserts `len(first.json()) == len(FILES)` so it is not vacuously empty (`:50`).
- `:56`: CSV compared in full the same way.
- No clock mocking or monkeypatching other than `zones.ALIASES_PATH` (`:29`), which points the aliases at a nonexistent temp file (keeps the real `config/zone_aliases.yaml` unread). `app/scoring.py` has no `datetime`/`time` use (grep), so nothing is hidden. [PASS]
- Note: both runs share one process, so hash-seed-dependent ordering could not be caught. Acceptable for this task's wording ("same db and needs").

## (2) Would fail on a mutation (reasoned from code)
- Removing `l["scoring_version"] = SCORING_VERSION` (`app/scoring.py:449`) → `l.get("scoring_version")` is `None`, so `== [2]*4` at `:61` fails.
- Dropping the CSV column (`app/main.py:657/663`) → `assert "scoring_version" in header` (`:65`) fails.
- Any value changing between calls (e.g. random tie-break or `now()` in a score) → `:51/:52` fails.
- Seeded data has 4 listings, so the version assertions cover real rows. [PASS]

## (3) Expected version
- `:61` `[2] * len(FILES)` and `:66` `["2"] * len(FILES)` are hard-coded literals; the docstring (`:5`) says the value is research R14's literal. `research.md:235`: "`SCORING_VERSION = 2`". Matches `app/scoring.py:20` `SCORING_VERSION = 2`.
- Acceptable under VII/VIII: the value comes from the spec, not from the code's output; importing the constant would be tautological. Cost: a legitimate future bump to 3 requires updating this test, which is intended. [PASS]

## (4) Data / isolation
- Fixtures: four files in `tests/fixtures/emails/` (all exist; `:19-24`), checked by the anonymise gate rules of the repo. `needs.example.yaml` is copied to `tmp_path` (`:35`), db is `tmp_path/t.db` (`:36`). No `data/`, `needs.yaml` or `zone_aliases.yaml` read.
- All three tests take `no_network` (`:45,55,59`).
- Import goes through `POST /api/alerts/import` with base64 content (`:37-40`), asserting `n_imported == len(FILES)`.
- Isolation env vars: the test does not need them (explicit temp paths), I ran pytest with all three set to `%TEMP%\casa-agent`. [PASS]

## (5) Handoff claims
- `pytest tests/test_article_viii.py` with isolation env vars: `3 passed in 17.37s`. Matches "tests passed on first run".
- Claim "`app/scoring.py` sets `l["scoring_version"]`": true (`app/scoring.py:449`). CSV column: `app/main.py:657,663`. [PASS]
- Claim of existing coverage in `tests/test_api_sorting.py` / `tests/test_api_units.py` not re-verified (not material).

## Notes (non-blocking)
1. `contracts/api.md:75` says `/api/listings` "response gains `scoring_version`" (top level), while the implementation and test put it per item and keep a plain list. The handoff discloses this; the user may want to decide if the contract wording should be aligned later. Not a T064 defect.
2. Handoff line 23 says gate/diff-scope results are "in the commit/report" but the file contains none; I ran the diff-scope check myself above (clean). I did not run compileall/full pytest/anonymise gates.
