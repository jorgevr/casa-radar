# T069 dev handoff: availability controls in the UI

Only `app/static/index.html` changed (no backend, no tests; there is no UI test runner).

## Changes
- Listing detail: button "Marcar como ya no disponible" (availability active/absent) or "Deshacer" (gone). Click calls
  `PATCH /api/listings/{encodeURIComponent(id)}` with `{"availability":"gone"|"active"}` via the existing `data-act` delegated
  handler (no inline handlers). The button is disabled while the call runs and a per-id `availBusy` set blocks a second submit;
  on success it toasts and `await renderRanking()` reloads `/api/listings`, so order and flags follow the API.
  Errors (Spanish toast): 404 not found, 400 invalid value, TypeError = no connection, otherwise the server message;
  the button is re-enabled.
- Table: `tr.gone` class for `availability === 'gone'` (muted text, dimmed bar/pill; rows stay listed, order is the API's).
  The Estado cell shows a `ya no disponible` pill and, if present in `eval.flags`, the `vuelto a ver en una alerta el <fecha>`
  flag in warn colour (not dimmed, so visible on a greyed row). Both also appear in the detail "Avisos" list as other flags do.
- Pure helpers: `isGone`, `relistedFlag`, `availError`.

## Backend check
`GET /api/listings` returns the DB row, so `availability` ('active'/'gone') is present; `eval.flags` carries
`ya no disponible` (first) and the stored relisted flag. Confirmed with TestClient on a temp DB (manual listing, PATCH gone,
re-GET: availability gone, flag present; unknown id 404; invalid value 400). Unknown/absent availability is treated as not gone.

## Decisions
- Greyed via colour/dimming on parts of the row instead of whole-row opacity (as `ex` does) so the relisted flag stays readable.
- The date in the relisted flag is shown exactly as the API text (already dd/mm/aaaa), only escaped.

## By hand in the browser (isolated env vars, `serve`)
1. Add a manual listing in Datos, open it in Oportunidades, click "Marcar como ya no disponible": row greys, pill appears,
   the row moves after active ones, detail shows "Deshacer" and the flag under Avisos.
2. Click "Deshacer": row returns to normal. Stop the server and click the button: "Sin conexión con el servidor local."
3. Check date columns, header sorting, "Fusionar con…" and the price history still work.
4. Relisted flag: import an alert for a gone listing dated after the mark; the warn text shows on the grey row.

## Reviewer should check
- Double submit guard and button re-enable on error; id encoding; escape of all inserted values.
- T030 code paths untouched (sortRows, date columns, merge, priceHist).
