# T042 dev handoff (app/static/index.html only)

Changes
- New "Características" block in the listing detail: bathrooms, floor, location_text show `desconocido` when null;
  elevator, terrace, garage, pool, garden show `desconocido` when null, `sí`/`no` only for real 1/0 values.
- Development listings (`l.development`): table row shows "(promoción)" next to the price (title = the label);
  the detail has a "Promoción" block with "precio de promoción, no de una vivienda: <precio>", the unit
  description (`desconocido` if null) and three inputs (precio, superficie, habitaciones) with button
  "Guardar vivienda elegida" -> `PATCH /api/listings/{id}` with only the filled fields.
- Client validation: price and area finite > 0 (comma accepted), bedrooms `^\d+$`; at least one field required.
  Server 400 shown as "Vivienda no válida (detalle: ...)". Request and re-render are in separate try blocks,
  button re-enabled on failure, double-submit guard (`unitBusy`), all dynamic text through `esc()`.
- Flags (Avisos) display as-is; `zona no reconocida...` gets the hint "Añade esta zona a
  config/zone_aliases.yaml para reconocerla." (file not read). `promoción: sin vivienda elegida` and the
  `... desconocido/a` flags need no change.

Decisions not in the docs
- Placeholders show the current values; empty fields are not sent (so a user can fix only the price).
- Row cells for m2/Hab already show `—` for null; left unchanged.

Checks: `node --check` of the inline script ok. Gates: see commit; no JS test harness exists.

Reviewer, click in a browser (run `serve` with CASA_DB/CASA_NEEDS/CASA_APPDATA in a temp dir, import a CSV
or alert fixture containing a development listing and one with an unrecognised zone):
1. Oportunidades -> open any row: "Características" shows `desconocido` for nulls, never "no" for null.
2. Open a promoción row: label "precio de promoción, no de una vivienda" next to price, unit description,
   and "(promoción)" in the table price cell.
3. Enter price `0`, area `-3`, bedrooms `1.5` -> red toast each time, no request. Enter `250000`, `90`, `3` ->
   "Vivienda guardada", row re-renders, flag "promoción: sin vivienda elegida" disappears.
4. Stop the server and press the button -> "Sin conexión con el servidor local.", button usable again.
5. Open a listing with an unknown zone: Avisos shows `zona no reconocida: "..."` plus the zone_aliases.yaml hint.
