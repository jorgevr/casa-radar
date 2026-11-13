# T061 dev handoff (UI, `app/static/index.html` only)

No automated tests (UI tasks, precedent T021/T030). Manual check: quickstart 3 and 5, run by the user.

## What changed

- **(a) Status bar, every tab.** New `#mbx` strip under the header: cuenta, carpeta, última sincronización correcta,
  último error con hora, "Sincronizar ahora", and "Sincronizando… N de M emails" while `running`
  (progress shown only when `total > 0`). Polls `GET /api/mailbox`. "Sincronizar ahora" -> `POST /api/mailbox/sync`:
  202 toast "Sincronización iniciada"; 409 `sync already running` / `mailbox not configured` / revoked each have their own
  fixed Spanish text; other 4xx/5xx and network failure have fixed text with the status code. When a sync goes from
  running to finished and the ranking tab is open, the ranking is re-rendered (keeps the open row).
- **(b) Out-of-date warning.** `#ood` above the ranking filters, shown when `out_of_date` is true and the mailbox is
  configured (see decisions). Mentions that the last attempt failed when `last_attempt_status` is present and not `ok`.
- **(c) Revoked banner.** On every tab when `auth_state === 'revoked'`: "Sincronización detenida: permiso revocado o
  caducado", automatic sync paused, and the `reauthorise_steps` from the API as an ordered list.
- **(d) Datos tab "Buzón (Gmail)" card.** `app_folder` path for `client_secret.json`; "Autorizar" (202 `{waiting:true}`, then
  polling until `auth_state` changes, or `last_error_at` changes (failed flow), or 5 minutes; waiting and timeout messages);
  label input + "Guardar etiqueta" (`PUT /folder`; 404 -> "Carpeta «X» no encontrada en Gmail.", 400/409/502/other mapped);
  the permission explanation in Spanish with `myaccount.google.com/permissions`; "Desconectar" behind `confirm()`.

## States handled

| state | status bar | extras |
|---|---|---|
| not configured | "Buzón no configurado — ve a Datos → Buzón"; sync button disabled | no out-of-date warning; no fake "sincronizado" |
| valid | account, folder, last success ("ninguna todavía" if null) | |
| running | "Sincronizando…" (+progress); button disabled; fast polling | ranking refreshes when it ends |
| out of date | as valid | warning above ranking |
| revoked | as above; sync button disabled | red banner with steps; Autorizar button reads "Autorizar de nuevo" |
| error | "Último error: <last_error> (hora)" | |
| API unreachable / non-200 | bar shows the error, no stale data | retries on the idle interval |

## Polling constants (named, top of the mailbox block)

`MBX_POLL_IDLE_MS = 60000`, `MBX_POLL_RUNNING_MS = 2000`, `MBX_AUTH_WAIT_MAX_MS = 300000`. One `setTimeout` chain (no
intervals): fast while running / sync request in flight / awaiting authorisation, idle otherwise. While the browser tab is
hidden and nothing is running or awaited, the request is skipped (timer keeps ticking). Stale responses are dropped by a sequence counter.

## Decisions the docs do not cover

- `mbxCall` uses `fetch` directly instead of `api()`, because `api()` reads `.detail` but the mailbox endpoints return `{"error": ...}`;
  the UI needs the body to tell the 409 causes apart. Only `/api/mailbox*` is called.
- Out-of-date warning suppressed when `auth_state` is `not_configured` (nothing to be out of date).
- The authorise flow can fail without changing `auth_state` (server records `last_error`), so the wait also ends when
  `last_error_at` changes, and shows that error text (class name only, from the server).
- Revoked: "Sincronizar ahora" disabled (server would return 409 anyway). Steps text from the API says "Pulsa «Autorizar de
  nuevo» en esta pantalla", but the button lives in Datos; the banner says where (Datos -> Buzón) and the button label matches.
- Label input is prefilled once from `label_name` and not overwritten after the user types.
- Unknown `auth_state` values are shown as-is (escaped), never mapped to ok.

## Verified

- Inline JS: `node --check` on the extracted script: OK.
- Real app in isolation (`$env:TEMP\casa-agent-T061-dev`, port 18761, temp DB/needs/appdata, no client_secret): page served,
  `GET /api/mailbox` returned the not-configured JSON. Seeded a revoked row with `alerts_sync.write_state` (with HTML in
  account and last_error) and screenshotted via headless Edge: status bar, red banner with the 4 steps, out-of-date warning
  above the ranking render correctly; HTML in server strings is shown escaped, not interpreted. Server stopped afterwards.
- Gates: see the final report of the coordinator message (compileall, pytest not slow, anonymise check, diff checks).

## NOT verified

- Not rendered: not-configured, running/progress, valid, and the Datos tab card (no click tool; only the revoked/out-of-date
  view was screenshotted). Authorise/sync/folder/disconnect flows were never exercised (they need Google or a client secret).
- Narrow-width layout (bar wraps via flex-wrap; only checked at ~1100 px).

## User manual check

Quickstart 3: place `client_secret.json` in the folder shown in Datos -> Buzón; enter the label, "Guardar etiqueta";
"Autorizar", approve in the browser, the card and bar switch to autorizado with your account; check the permission text.
Quickstart 5: after revoking at Google, "Sincronizar ahora" -> red banner + steps on every tab + warning above the ranking;
"Autorizar de nuevo" resumes. Wrong label -> «Carpeta … no encontrada». "Desconectar" asks for confirmation and returns to
"Buzón no configurado". Network off -> last error with time; warning appears after 30 minutes.
