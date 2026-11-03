# T036 dev handoff

Files: `app/static/index.html` only (no backend change; every field needed is already returned).

## Changes
- Datos tab, first card "Categorías de alerta": editable rows (`contiene`, categoría), "Añadir regla", "Quitar" per row, "Guardar reglas".
  Save: client check for empty text/category (message "La regla N no tiene ..."), then `PUT /api/categories {"rules":[...]}` (trimmed). Button
  disabled during the call and a `catSaving` guard blocks double submit. 400 -> "Reglas no válidas: <server message>"; 500 -> "El servidor no pudo
  guardar ..."; network -> "Sin conexión ...". Success: toast and the section is reloaded from `GET /api/categories`.
  Below: table of stored search names (name, category, email count); null/`unknown` category shows "sin categoría / desconocida".
- Ranking reload: the ranking tab always refetches `/api/listings` when opened (`render()`), so categories re-derived by the PUT show there
  on the next visit; nothing is cached, hence no extra call after saving rules.
- Detail: new "Obra nueva" block (shown also when there is no mortgage estimate) with current state (obra nueva / segunda mano / desconocido +
  origin). If `new_build_origin==='category'`: flag text + "Confirmar obra nueva" (PATCH true) and "Es segunda mano" (PATCH false). Otherwise
  "Marcar obra nueva" / "Marcar segunda mano"; "Quitar mi valor" (PATCH null) only when origin is `user`. Body is a real JSON boolean/null,
  id via `encodeURIComponent`, all nb buttons disabled during the call plus a busy set, Spanish errors for 400/404/network, then `renderRanking()`
  (cost estimate IVA+AJD vs ITP refreshes).
- Flags: `encontrado vía: ...`, `búsqueda desconocida`, `reglas de categoría en conflicto: ...` come in `eval.flags` and render in "Avisos" as before
  (server already de-duplicates). The `obra nueva según la categoría ..., confirma` flag is removed from "Avisos" and shown only in the Obra nueva
  block, so it is not shown twice.
- No inline handlers built from data; delegation on `#cat` and the existing `tbody` handler. All inserted values go through `esc`.

## Decisions
- "Obra nueva" block is a separate grid cell (not inside the mortgage cell) because `eval.mortgage` can be null.
- Page does not reflect the PATCH optimistically; it reloads.
- `new_build_origin` values `email`/`category`/`user` get a Spanish label; other/null show no origin.

## Verification
- `node --check` on the extracted script: OK. Node script with a stubbed DOM exercised `rulesProblem`, `cleanRules`, `catSearchRows` (escaping, unknown label) and `detail()`
  (category flag appears once, buttons per origin, "Quitar mi valor" only for user, "desconocido" for null). Prints ok.
- TestClient with isolated CASA_* and `categories.CATEGORIES_PATH` patched to a temp file: `/`, `/api/listings`, `/api/categories` 200; PUT valid 200, empty text 400.
- Not done: clicking in a real browser (no runner).

## By hand
Run `serve` with the isolated env. Datos: add a rule, save with an empty field (client message), save valid (toast, table reload), look at the search-name table.
Open a listing from a `new-build` category alert: flag + two buttons; confirm -> origin becomes user, "Quitar mi valor" appears, cost estimate changes.

## Reviewer
- `catClick`/`drawCat` redraw from the `catRules` model (inputs sync through `oninput`).
- Saving through the real app writes the tracked `config/alert_categories.yaml` (intended); not triggered in tests.
