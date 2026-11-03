# FU3 review 1 (app/static/index.html, commit ed56981)

Gates (isolated CASA_* under %TEMP%\casa-agent\FU3-review): compileall OK; pytest -q -m "not slow" 319 passed; anonymise check OK;
forbidden-path diff vs jorgevr/spec-kit-3-feature...HEAD lists only index.html and FU3-dev.md; requirements.txt diff empty.
Note: ref `jorgevr/spec-kit` does not exist in this worktree, so the feature branch was used as base.

## Per ask
1. Save button re-enabled in finally: OK (index.html:203). Fresh lookup handles a redrawn view; catSaving also reset.
2. Edits typed during a PUT: OK (:197-201). Snapshot compared via cleanRules after await; add/del blocked by catSaving, input handler (:214) keeps catRules live. Minor: in the "changed" branch the saved-searches table (catNames) is not refreshed, so category column is stale until next load.
3. PATCH separate from render: done for new-build only (:103-106). NOT applied to other call sites (see findings 1-3).
4. Prefix + "(detalle: ...)": done for availError, nbError, catErr, merge. Other server-text sites not converted (finding 4).
5. Merge double-click guard: OK (:108-111). confirm() is synchronous so no interleave; busy cleared on failure.
6. NB_FLAG: OK (:35-36), matches app/scoring.py:174 exactly, defined before both uses (:65, :130).

XSS: no new unescaped HTML. toast uses textContent; catmsg messages go through esc(); nb flag via esc(). No issue.

## Findings
1. app/static/index.html:99 (avail toggle): PATCH and `await renderRanking()` are in one try. If the re-render fails after a successful PATCH, the catch shows "No se pudo cambiar la disponibilidad (detalle: ...)" although the change was saved, re-enables the button, and the user may retry/undo wrongly. Same pattern ask 3 targeted; missed call site.
2. :112-113 (status / amenities): `renderRanking()` inside the try with the API call; render failure shows raw err.message and sets button to "Reintentar", prompting a repeat of an already-applied action (e.g. second OSM lookup).
3. :142 (zone indicators PUT + renderZones) same combined try; render failure reported as a save failure.
4. Unprefixed raw server/JS text still shown: :113, :142, :159, :211 `toast(err.message,1)`; :180 and :192 use a different "...: text" form instead of "(detalle: ...)". Inconsistent with ask 4 (English server text can reach the user with no Spanish prefix). Low severity.
5. :101-106: if renderRanking throws after a successful nb PATCH, the nb buttons disabled at :102 are never re-enabled (only the catch of the PATCH re-enables). The message says reload, so recoverable, but it is a stuck state until reload. Low.
6. :110: on merge success the clicked button stays disabled and renderRanking() is not awaited/caught (unhandled rejection, no user message if render fails). Low.
7. Handoff admits no browser/JS harness; none of the new behaviour (race on PUT, disabled states) is tested. Acceptable per project (no JS test infra) but unverified.

STATUS: FAIL
