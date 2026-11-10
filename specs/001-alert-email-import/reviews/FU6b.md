# FU6b review 1: partial failure in "Emails no importados" + detail panel layout

Scope: `git diff jorgevr/spec-kit-3-feature...HEAD` (HEAD 10c9151): `app/static/index.html`, `handoffs/FU6b-dev.md`.

## Gates (isolated CASA_* under %TEMP%\casa-agent\FU6b-review)
- compileall ok. `pytest -q -m "not slow"`: 474 passed, 1 deselected. anonymise check rc 0.
- Diff lists only index.html and the handoff; requirements.txt diff empty. `node --check` of the extracted inline script: ok.

## 1. Partial failure (loadEm / drawEm, index.html ~236-250)
- Each list is requested independently (`.then(ok, err)` per list), so one rejection no longer hides the other. The loaded list is rendered; the error line names the failed list ("fallidos"/"rechazados"); network TypeError gives "Lista de emails X: Sin conexión..." (errTxt with empty prefix). OK.
- Both fail: `bothFailed = errs.length===res.length` shows both errors and one Reintentar, no table and no "No hay emails" text. OK.
- Reintentar is `data-em="reload"`, handled by emClick -> loadEm (ignored only while a reprocess is running, same as Recargar). The button lives inside the re-rendered `#em`, so it is replaced on every redraw; there is no disabled state to restore and nothing stuck. OK.
- Stale guard: `my=++emSeq` before the requests, checked after the awaits and `#em` presence checked; a retry racing a tab switch or another Recargar drops the older response (renderData recreates `#em`; the old call sees a changed seq or a missing node). OK. Request and render are in separate scopes; render errors go through esc(renderWarn).
- All dynamic text (error messages, subject, reason, date, outcome) goes through esc(); the href uses encodeURIComponent. OK.
- Empty and success states unchanged (rows.length branch kept; errors block only when errs non-empty).

## 2. Detail panel layout (detail(), index.html ~150-160)
- Cause confirmed from the screenshot: "Fuente", "Emails de alerta" h3, the `<ul>`, "Historial de precios" h3 and `#ph` were bare grid children, each its own cell, so headings were separated from their content (list in a different column, price rows under the score block).
- Fix: `<div>`{Fuente + Emails de alerta h3 + ul}`</div>` and `<div>`{h3 Historial + #ph}`</div>`; each heading is now in the same block as its content. Tag count in the changed strings: srcLine p balanced; `<div>` opened before srcLine and closed at the start of the next template (`</div><div>...</div>`), balanced; OSM block `<div>...</div>` then one extra `</div>` that closes `.grid` (opened at the start of detail), same as before. Nothing unclosed or mis-nested.
- Narrow widths: still `.grid` auto-fill minmax(210px,1fr); cells just wrap, and the new wrappers are plain divs. Fine.
- Score components, Hipoteca, attr/dev/nb blocks, OSM services, price history, Avisos and "No cumple" are unchanged in content and order; only the two wrappers were added, `margin-top:0` on the Fuente paragraph.
- Link colour: `.det a{color:var(--acc)}`; `.det` is only the tr of the detail row (index.html:107), so other links are untouched. Contrast: light #1f5f4a on #f6f5f2 about 7:1; dark #6bbf9d on #161614 about 9:1. Adequate on both themes. Side effect: any other link inside the detail panel also becomes accent (intended).

## Findings (minor, non-blocking)
1. index.html drawEm: `emSummary` from an earlier reprocess still shows above partial errors; cosmetic (already noted in T046 review item 3).
2. The render-error fallback in loadEm has no Reintentar (pre-existing).

STATUS: PASS
