# FU3 dev handoff (app/static/index.html only)

1. Rules editor save: `finally` always clears `catSaving` and re-enables the save button (looked up fresh, in case the view was redrawn).
2. Save snapshot: the cleaned rules are snapshotted before the PUT; after success the form is reloaded only if the rules are unchanged, otherwise the user's newer edits stay and a "cambios nuevos sin guardar" notice is shown.
3. New-build PATCH and `renderRanking()` are separate try blocks; a failed re-render shows its own "guardada, pero no se pudo actualizar la vista" message.
4. Server errors now read `<Spanish prefix> (detalle: <server text>)` in availError, nbError, catErr and merge.
5. Merge: `mergeBusy` set + button disabled while POST is in flight; cleared on failure.
6. `NB_FLAG` moved to the top of the script with a comment pointing at app/scoring.py (the only place that matches it is the `fl` filter and the nbBlock warning).

Checks: node --check on the inline script OK; pytest -m "not slow" (see commit report). Reviewer: no JS harness, behaviour not exercised in a browser.

## Round 2 (review 1 fixes)
- PATCH/POST/PUT and the re-render are now separate try blocks at every site: availability toggle, status/amenities, zone indicators, new-build, merge. A failed re-render shows `renderWarn` ("Guardado, pero no se pudo actualizar la vista (detalle: ...)") and never a save failure or a "Reintentar" prompt.
- Stuck states: new-build buttons re-enabled if the render throws; availability button re-enabled likewise; on merge success the button is re-enabled and `renderRanking()` is awaited with its own error message.
- New helper `errTxt(prefix, err)` gives "<prefijo> (detalle: ...)" (or the offline message for TypeError). Applied to the raw `toast(err.message)` sites (status/amenities, zones, needs, mortgage, CSV import `go`) and the data-import and category-load messages.
- Not done: finding 2 minor (catNames not refreshed when edits were typed during a save). Gates: base ref is jorgevr/spec-kit-3-feature; diff lists only index.html, FU3-dev.md and the review file (coordinator's); requirements.txt diff empty.
