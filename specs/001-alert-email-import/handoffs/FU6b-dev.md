# FU6b dev handoff

File changed: `app/static/index.html` only. No JS test harness; inline script checked with `node --check` (OK) and the pytest suite.

## 1. Emails no importados: partial failure (T046 review finding 1)
`loadEm` now requests the two lists independently (each request has its own rejection handler). Each failure becomes a specific message:
`No se pudo cargar la lista de emails fallidos (detalle: …)` / `… rechazados …`. On a network TypeError (errTxt gives the generic "Sin conexión" text) it is prefixed `Lista de emails fallidos: Sin conexión con el servidor local.`
- One list fails: the loaded list is shown in the table, plus the error line and a `Reintentar` button (`data-em="reload"`).
- Both fail: both errors and one `Reintentar`; no table and no "No hay emails…" text.
- Success/empty: unchanged.
- `emSeq` stale guard kept (checked after the awaits); the request and the render are in separate try scopes (render has its own try/catch with renderWarn); all dynamic text through `esc()`.

## 2. Detail panel layout (screenshot): real bug, fixed
Cause: inside `<div class="grid">` (auto-fill columns) the `Fuente` paragraph, the `Emails de alerta` h3 + ul, the `Historial de precios` h3 and `#ph` were bare siblings, so each became its own grid cell and flowed into different columns/rows than its heading. Fix: wrap `Fuente` + `Emails de alerta` in one `<div>`, and `Historial de precios` + `#ph` in one `<div>`. Same data and wording; the `Fuente` line only gets `margin-top:0`.
Link colour: there was no `a` rule (default browser blue). Added `.det a{color:var(--acc)}`, scoped to the detail panel so the other links are untouched. The theme has no dedicated link variable, so `--acc` is used.

## Reviewer click-through
1. Start `serve` with CASA_DB/CASA_NEEDS/CASA_APPDATA in a temp folder; open Oportunidades with a listing that has sightings (or import an anonymised fixture email); click a row.
2. Check: under the table, "Emails de alerta" is directly above its list and "Historial de precios" directly above its price rows (with Actual); "abrir anuncio ↗" is the green accent, readable in dark mode.
3. Datos tab, partial failure: in devtools use request blocking (or temporarily make one URL fail) for `/api/alerts/emails?outcome=rejected` and click `Recargar`: the failed table remains, with "No se pudo cargar la lista de emails rechazados (detalle: …)" and `Reintentar`. Unblock, click `Reintentar`: error disappears. Repeat blocking `outcome=failed`, then both: two errors, no table.
4. Click Recargar twice quickly: only the last response renders.

## Gates
See the commit run: compileall, pytest -m "not slow", anonymise check, forbidden-path diff, requirements diff (results reported in the final message).
