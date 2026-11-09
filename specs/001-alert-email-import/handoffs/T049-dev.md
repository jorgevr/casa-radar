# T049 dev handoff

## Changed
Only `app/static/index.html`, Oportunidades tab.
- New module state `onlyNew` (default false), `rankSeq` (sequence counter), `newBusy`.
- New `fetchRanking()`: increments `rankSeq`, fetches `/listings` (plus `?new_since_last_run=true` when `onlyNew`) and `/needs`, returns `{L,N,stale()}`.
- `renderRanking(pre)` uses preloaded data or fetches; returns silently if the response is stale (a newer request started), so an older response never overwrites a newer one. This protects every caller (sort, "mostrar descartados", edits).
- Toolbar checkbox `#nw` "Solo nuevos desde la última sincronización/importación". Handler: guard `newBusy`, disables checkbox, fetch in one try (on failure reverts `onlyNew`, toast `errTxt('No se pudo aplicar el filtro de nuevos', err)`), re-render in a separate try (`errTxt('No se pudo mostrar la lista', err)`), re-enable in finally.
- Empty result with filter on shows "No hay anuncios nuevos desde la última sincronización o importación." instead of the generic "Aún no hay anuncios" card. Header count gets " (solo nuevos)".
- State is a module variable: survives re-renders (edits, sort) and tab switches within the session; resets on page reload.

## Decisions
- `renderRanking` is the only place that loads `/listings`; there is no separate merge picker or detail loader (detail uses the same list; merge button uses the id from the flag). So no other caller needed an unfiltered fetch. Consequence: with the filter on, an opened detail row exists only if that listing is in the filtered set; `open` stays set and reappears when the filter is off.
- Header count with filter on counts the filtered list.
- No new text escaping needed (all new strings are static constants).

## Reviewer / user check by hand in the browser (not tested in a browser)
1. Toggle on with a recent import: only new listings appear; off: full list returns.
2. Toggle on with no new listings: specific Spanish message, no generic card.
3. With toggle on, edit a listing / sort / open detail: filter stays on. Switch tab and come back: still on.
4. Stop the server, toggle: error toast "Sin conexión...", checkbox reverts.
5. Rapid clicks: checkbox is disabled during fetch.

## Verification
- Inline script syntax checked with `node --check` (OK). No JS unit tests exist for this; no static-HTML test in tests/.
- Gates: see commit report (compileall, pytest full, anonymise check, diff scope, requirements diff).
