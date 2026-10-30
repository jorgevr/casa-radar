# T021 dev handoff: alert email import in the Datos tab

No automated tests for T021, by the user's decision (covered by quickstart section 2, manual).

## What changed (only `app/static/index.html`)
- Datos tab: new card "Importar emails de alerta" with a multi-file picker (`accept=".eml,.mbox"`) and an
  "Importar emails" button. Files are read with `FileReader.readAsDataURL` (no call-stack issue on large files),
  the data-URL prefix is stripped, and `{files:[{name, content_base64}]}` is POSTed to `/api/alerts/import`
  through the existing `api()` helper. The button is disabled while uploading (re-enabled in `finally`).
- Result: one line per problem (FALLO for `failed`, RECHAZADO for others), then AVISO per notice, then
  "N emails: X importados, Y ya procesados, Z rechazados, W fallidos" and
  "anuncios: N nuevos, N actualizados (N cambios de precio)". Same wording and plural rule as the CLI
  (singular only for exactly 1). No "sin cambios" and no total are shown.
- Errors: 400 shows the server's fixed Spanish `detail` (it never contains file contents); a network failure
  (fetch TypeError) shows "sin conexión con el servidor local". Empty selection shows a hint.
- Everything email-derived (subject, reason, text, email_id, date, file names) goes through the page's existing `esc()`.
- Listings refresh: `renderRanking()` re-fetches `/api/listings` every time the Oportunidades tab is opened, so
  imported listings appear there; no extra call needed from the Datos tab.
- Listing detail: a line "Fuente: Idealista · visto por primera vez: <first_seen|desconocido> · última vez:
  <last_seen|desconocido>" (other sources show their raw source value, escaped; null source = desconocido).

## Part (2) deferred to T029
`GET /api/listings` today returns the raw `listings` row (minus `raw`) plus `eval`: only `source`, `first_seen`,
`last_seen` exist. There is no `sightings`/`links`, so the email subject(s) and the email date(s) cannot be shown
yet, and I added no dead code for them. Also deferred: the exact label "Idealista (email de alerta)". Rows created
by the idealista-mcp provider (`idealista_mcp.py`) also have `source='idealista'`, so with today's payload the
label "(email de alerta)" would be false for them; I show plain "Idealista". T029 should add the sightings/links
fields and then this line can show the email label, dates and subjects.

## Evidence
- (a) Inline script extracted to `%TEMP%\casa-agent-T021\page.js` (outside the repo): `node --check` OK.
- (b) Isolated env (CASA_DB/NEEDS/APPDATA under `%TEMP%\casa-agent-T021`), `python -m app.cli serve --port 8791`:
  `GET /` 200 and contains the new card. `POST /api/alerts/import` with base64 of the first two fixtures returned
  exactly the fields the page reads (n_found 2, n_imported 1, n_rejected 1, n_new_listings 1, problems[0] with
  email_id/alert_date/subject/outcome=rejected/reason, notices []). `GET /api/listings` then had 1 listing with
  source `idealista`, first_seen/last_seen `2026-07-20`. `{"files":[]}` returned 400 with the Spanish detail.
  Server stopped; no `app.cli serve` process left.
- (c) No browser automation tool was used (none driven by me), so NO click-through of the picker was done.
  Manual steps for the user: `serve` (with isolated env or your own), open the page, Datos tab, choose
  several `.eml` from `tests/fixtures/emails`, click "Importar emails": expect a RECHAZADO line for the 2021
  email and the totals; select a `.txt` or `.msg` file for a FALLO line; re-import the same files for
  "ya procesados"; open Oportunidades and expand a listing to see the "Fuente" line; stop the server.

## Gates
compileall OK; pytest not slow 106 passed; slow 1 passed; anonymise check exit 0; diff names and requirements.txt
checked before commit (see report).

## Reviewer should check
- Escaping of every interpolated value in `importLines`, `importAlerts` and the detail line.
- That the error path never echoes file contents.
- The decision to show plain "Idealista" instead of "Idealista (email de alerta)".
- Large multi-file uploads: whole request is one JSON body (no chunking across requests).
