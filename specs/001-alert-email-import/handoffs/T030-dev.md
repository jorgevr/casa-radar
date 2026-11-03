# T030 dev handoff

File changed: `app/static/index.html` only.

## Changes
- Oportunidades: columns Publicado / Actualizado (dd/mm/aaaa, "desconocido" when null). Dates are formatted with a regex on the ISO string (no `new Date`, no timezone shift).
- Header click on Publicado / Actualizado sorts client-side, toggling asc/desc; unknown dates are always last in both directions (stable among themselves). Header Score resets to the API order (default = score).
- Detail: "Historial de precios" loaded from `GET /api/listings/{id}/price-history` (id via `encodeURIComponent`); `alert_previous` rows show "antes del <fecha>", then a bold "Actual" row with the listing price. Load errors show a Spanish message.
- Detail: source "Idealista (email de alerta)" when the listing has sightings, plus a list of email date and subject per sighting (escaped, `esc`).
- "Fusionar con..." button next to each `posible duplicado de <id>` flag: confirm dialog, POST merge `{into: <id>}` (this listing merges into the flagged one), then reload. 404 / 409 / 400 map to Spanish toasts. `api()` now sets `err.status`.

## Decisions
- Merge direction: the open listing is merged INTO the flagged one (the docs do not say which; reviewer may flip).
- Only Publicado, Actualizado and Score headers are sortable (task scope).
- Sort state is kept in memory (resets on reload).

## Check by hand (quickstart section 4)
Import alert emails, open Oportunidades: dates show; click Publicado twice (asc, desc), listings without date stay at the bottom; click Score to restore. Open a listing with a price drop: "antes del ..." row; a duplicate flag shows "Fusionar con...".

## Verification done
node --check on the extracted script; node check of sort/date helpers (unknown last both directions, 2025-01-09T23:30 -> 09/01/2025); TestClient served `/` and `/api/listings` with temp env. Rendering in a real browser was not done.

## Reviewer checks
Escaping of subjects/ids/flags; data-into attribute escaped; no raw data in innerHTML.
