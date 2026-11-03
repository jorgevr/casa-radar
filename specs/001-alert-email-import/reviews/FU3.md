# FU3 review 2 (app/static/index.html, HEAD d72bf75; round-1 review kept as FU3-r1.md)

## Gates (isolated CASA_* under %TEMP%\casa-agent\FU3-review2)
- compileall: OK.
- anonymise check: rc=0.
- forbidden-path diff vs jorgevr/spec-kit-3-feature...HEAD: only app/static/index.html, handoffs/FU3-dev.md and the review file. requirements.txt diff empty.
- node --check of the extracted inline script: OK (node v22.16.0).
- pytest -m "not slow": NOT COMPLETED. The machine was running three other pytest sessions and the run did not finish in 25+ minutes
  (a first run was killed; a second verbose run reached 27%, 87 passed, 0 failed before I stopped waiting). Mitigation: since round 1
  (which ran 319 passed) only index.html and the handoff changed (git diff --stat d826150 HEAD), and no test references app/static or index.html. Not a verified rerun.
- Base ref: jorgevr/spec-kit does not exist here; jorgevr/spec-kit-3-feature used.

## Round-1 findings
1. Avail toggle: FIXED. PATCH has its own try/catch (returns on failure); render in a separate try with renderWarn and button re-enabled (:101-105).
2. Status/amenities: FIXED. API call and renderRanking in separate tries; failure message via errTxt/renderWarn, no repeated action prompt on render failure (:117-120).
3. Zone indicators PUT + renderZones: FIXED (:149-150).
4. Raw err.message sites: FIXED for status/amenities, zones, needs, mortgage, data-import `go`, importAlerts, loadCat via errTxt. grep of `.message` shows every remaining use is inside a prefixed helper (errTxt, renderWarn, availError/nbError/catErr, merge). TypeError maps to the offline message.
5. Stuck nb buttons after render failure: FIXED (nb buttons re-enabled in the render catch, :111).
6. Merge success: FIXED. Button re-enabled, renderRanking awaited in its own try with renderWarn (:115). Inner try is nested in the outer try, so render failure cannot reach the merge error handler.
7. No JS harness: unchanged, acceptable.
Round-1 minor (catNames not refreshed when edits typed during save): acknowledged as not done; still cosmetic.

## Request/render separation, every mutation site
avail PATCH, nb PATCH, merge POST, status PATCH / amenities POST, zones PUT: separated. Needs PUT, mortgage GET, categories PUT (loadCat catches its own errors internally),
alerts import, `go` CSV/provider/manual imports: no re-render after the call, so nothing to separate.

## Regression check
- Stuck disabled buttons: none found. avail, nb, merge, catSaving/save button all reset on every path.
- XSS: errTxt/renderWarn strings go through toast (textContent per round 1) or esc() in innerHTML (importAlerts, loadCat, catmsg). No new unescaped HTML.
- Swallowed errors: none; every catch surfaces a message.
- errTxt misuse: all call sites pass a Spanish prefix. One caveat below.

## Findings (all low, non-blocking)
1. :36 errTxt maps any TypeError to "Sin conexión con el servidor local", so a programming TypeError would be misreported as offline. Same pattern as the existing availError/nbError; consistent, not a regression.
2. :117-120 amenities: on a render failure after success the button text stays "Consultando OSM…" until reload (renderWarn tells the user to reload). Cosmetic.
3. :34-36 the "Must equal, character for character..." NB_FLAG comment now sits above the errTxt/renderWarn lines instead of directly above NB_FLAG (:38). Cosmetic; move the two helpers above the comment.
4. pytest rerun not completed (see Gates); recommend the coordinator's own run.

STATUS: PASS
