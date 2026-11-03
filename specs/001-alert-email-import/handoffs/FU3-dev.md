# FU3 dev handoff (app/static/index.html only)

1. Rules editor save: `finally` always clears `catSaving` and re-enables the save button (looked up fresh, in case the view was redrawn).
2. Save snapshot: the cleaned rules are snapshotted before the PUT; after success the form is reloaded only if the rules are unchanged, otherwise the user's newer edits stay and a "cambios nuevos sin guardar" notice is shown.
3. New-build PATCH and `renderRanking()` are separate try blocks; a failed re-render shows its own "guardada, pero no se pudo actualizar la vista" message.
4. Server errors now read `<Spanish prefix> (detalle: <server text>)` in availError, nbError, catErr and merge.
5. Merge: `mergeBusy` set + button disabled while POST is in flight; cleared on failure.
6. `NB_FLAG` moved to the top of the script with a comment pointing at app/scoring.py (the only place that matches it is the `fl` filter and the nbBlock warning).

Checks: node --check on the inline script OK; pytest -m "not slow" (see commit report). Reviewer: no JS harness, behaviour not exercised in a browser.
