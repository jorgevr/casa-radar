# T046 dev: Datos tab "Emails no importados"

File: `app/static/index.html` only (new card `#em` after the categories card; functions `drawEm`, `loadEm`, `emClick`).

- Loads `GET /api/alerts/emails?outcome=failed` and `rejected` in parallel, merges, sorts newest first by `alert_date`.
- Table: Fecha, Asunto, Motivo, Estado (Fallido/Rechazado), "Descargar original" link (`/api/alerts/emails/<encodeURIComponent(id)>/raw`, `download`). Raw content is never injected. All dynamic text goes through `esc()`.
- Empty list: "No hay emails fallidos ni rechazados." Load error: `errTxt('No se pudieron cargar los emails', er)` plus "Reintentar" button. Request and draw are in separate try blocks.
- "Reprocesar": POST `{scope:"failed"}` only (scope "all" deliberately not offered). Double-submit guard (`emBusy`), button re-enabled in `finally`, summary rendered with the existing `importLines` (leídos/importados/ya procesados/rechazados/fallidos, plus problems), then table reloaded. Error: `errTxt('No se pudo reprocesar', er)`.
- Stale responses: `emSeq` counter; a response whose sequence is not the latest, or whose `#em` no longer exists (tab re-rendered/left), is dropped. Re-rendering Datos re-creates `#em` and calls `loadEm()`; handler rebound via `$('#em').onclick`.
- Decision: the summary text is kept in `emSummary` (module state) so it survives the reload redraw; it also shows again if the Datos tab is re-opened in the same page session.

Gates: node --check of extracted script OK; compileall OK; pytest -m "not slow" 469 passed; anonymise check rc=0; diff vs jorgevr/spec-kit-3-feature lists only index.html (+ this handoff); requirements.txt diff empty.

## Reviewer click-through (isolated CASA_* env, `python -m app.cli serve` or equivalent, no real mailbox)
1. Open Datos: card "Emails no importados" appears under "Categorías de alerta". Empty DB: shows the empty message.
2. Import (card below) a failing/rejected anonymised .eml from `tests/fixtures/emails` or a deliberately malformed one; click "Recargar": row appears with date, subject, reason, state.
3. Click "Descargar original": browser downloads `email.eml`; page unchanged.
4. Click "Reprocesar": button disabled while running, then summary line counts appear and table reloads.
5. Stop the server and click "Recargar": offline message plus "Reintentar"; restart and Reintentar loads the table.
6. Switch to another tab and back during a load: no duplicate/stale table, no console errors.
