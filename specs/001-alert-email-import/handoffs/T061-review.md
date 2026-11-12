# T061 review (UI, `app/static/index.html`)

**Verdict: [PASS]** — no blocking defects. Four non-blocking items (N1–N4) should be fixed or accepted before the user's manual check; N1 will be hit directly by quickstart §3.

Scope read: AGENTS.md, FR-028/029, contracts/api.md (Mailbox), contracts/mail-source.md, quickstart §3/§5, T061-dev.md, full diff vs `jorgevr/Implementation`, `app/main.py:471-596`. Read-only; nothing in the repo was changed (only this file added, uncommitted).

## Rendering evidence (headless Edge, isolated)
Env: `$TEMP\casa-agent-T061-review` (CASA_DB/NEEDS/APPDATA, needs.example.yaml copy), port 18771, app created with `create_app()` (no scheduler), states seeded with `alerts_sync.write_state`. A throw-away wrapper outside the repo served a copy of index.html with the initial `tab` swapped so the Datos tab could be shown. No Autorizar/Sincronizar/Guardar/Desconectar clicked. Server stopped afterwards (verified down).

| State | Rendered? |
|---|---|
| not-configured (ranking + Datos tab, Buzón card) | rendered (card seen on Datos) |
| valid, never synced ("ninguna todavía") | rendered |
| running with progress ("Sincronizando… 3 de 12 emails") | rendered |
| out-of-date + last error (with HTML in `last_error`) | rendered, escaped |
| revoked on Datos tab (banner + 4 API steps, "Autorizar de nuevo", HTML in account/last_error) | rendered, escaped |
| revoked on ranking tab | rendered (seeded; banner identical code path, `ban` is outside `#main`) |
| Authorise / folder / sync / disconnect flows, timeouts, fetch failure, narrow width | **read only** |

## (1) XSS — every innerHTML assignment
`esc` = `index.html:43` (escapes `& < > " '`).
- `#mbx` `el.innerHTML` (L~320-325): `mbxErr` is a constant + numeric status, wrapped in `esc()`; `m.account`, `m.label_name`, `esc(fmtTs(..))`, `esc(m.last_error)`, `esc(m.last_error_at)`, `esc(p.done)`, `esc(p.total)` all escaped; `title="..."` attributes are constants. `fmtTs` returns digits or "desconocido". OK.
- `ban.innerHTML` (revoked): `m.reauthorise_steps.map(x=>`<li>${esc(x)}</li>`)`; rest constant. OK.
- `drawOod` `el.innerHTML`: `esc(fmtTs(mbx.last_success_at))`; `last_attempt_status` is only compared, never printed. OK.
- `#mbs` (`drawMbc`): `mbxState(mbx.auth_state)+(mbx.account?' · '+esc(mbx.account):'')`; `mbxState` = constants or `esc(a)`. OK.
- `#mbmsg` `innerHTML=...authMsg`: every assignment to `authMsg` is a constant string or goes through `esc()` — `'...'+mbxState(..)+'...'` (esc'd), `esc(mbx.last_error)`, `esc(r.status===0?...)`, and the folder message `authMsg=t?`<span class="bad">${esc(t)}</span>`` where `t` embeds the user-typed `name` (`'Carpeta «'+name+'» no encontrada…'`) — escaped by that `esc(t)`. OK.
- `#mbf` uses `textContent`; `#mbl` set via `.value`; `toast` uses `textContent`. No server/user string reaches an attribute unescaped.
- Visual proof: `<img src=x onerror=alert(1)>`, `<i>z</i>`, `<b>x</b>` shown literally in the screenshots.
- `render()` catch (pre-existing) uses `esc(e.message)`. The `{error:...}` bodies of the mailbox API are never displayed; only fixed Spanish text + status codes.

## (2) Contract fidelity
Fields used: `auth_state, running, progress.{done,total}, reauthorise_steps, app_folder, last_success_at, last_error, last_error_at, label_name, account, out_of_date, last_attempt_status` — all exist in `main.py:489-500`. `auto_sync` is not displayed (not required).
- authorise 202 only; other → message with code. Folder: 200/404/400/409/502/0/other all mapped (L367). Sync: 202 toast; 409 split by exact error strings that match `main.py:551/553/555`; other → code text. Disconnect 200 vs else. OK.
- N1 below: the card lists save-label before authorise, but `PUT /folder` needs a token.

## (3) Honesty
- not-configured: "Buzón no configurado — ve a Datos → Buzón…", no "sincronizado", no OOD banner. Verified render.
- never synced: "Última sincronización correcta: ninguna todavía" — verified. Absent account → "desconocida", label → "sin elegir", unknown state → "desconocido", bad timestamp → "desconocido".
- running, OOD, revoked, error render truthfully (screenshots). Dates dd/mm/yyyy hh:mm; page uses dd/mm/yyyy (`fmtDate`), time added — consistent.
- Non-blocking observation: configured but never synced shows no out-of-date warning (server `out_of_date` is false there); the bar still says "ninguna todavía", so nothing is claimed falsely.

## (4) Timers
Constants `MBX_POLL_IDLE_MS/RUNNING_MS/AUTH_WAIT_MAX_MS` named. One `setTimeout` chain; every `mbxSchedule()` does `clearTimeout(mbxTimer)` so handler-triggered refreshes cannot stack; `mbxSeq` drops stale responses; fetch errors are caught in `mbxCall` (status 0) and shown in the bar; hidden tab skips requests unless running/awaiting. No `setInterval`. 5-minute authorise stop at L341. Issues: N2, N3.

## (5) Placement
`#mbx` and `#ban` are outside `#main` (above `<main>`), so they show on every tab (Datos, ranking verified). `#ood` is the first child of the ranking HTML (L104) and `drawOod()` is called after the `innerHTML` assignment. The revoked banner prints the API's steps (4 items rendered).

## (6) Confirmations / double submit
`Desconectar`: `confirm('¿Desconectar el buzón? …')` before the POST. `Sincronizar ahora`: disabled when `nc||revoked||run||syncBusy` (L324) and guarded in `syncNow`. `Guardar etiqueta`: `folderBusy`. `Autorizar`: see N2.

## (7) Secrets / network
No localStorage/sessionStorage, no token handling, no external URL (`grep https?://` finds none in the new code; only the text `myaccount.google.com/permissions`). Only `/api/mailbox*` fetched. The `app_folder` path is shown by design (contract).

## (8) Existing features
Removed lines (4): the ranking filter-row template (only `<div id="ood"></div>` prepended), `h+='</tbody>…';$('#main').innerHTML=h;` (only `drawOod();` appended), `renderData` template start (Buzón card inserted before `#cat`), `loadCat();loadEm();` (only `mbcInit();` prepended). All are necessary hooks; no behaviour removed.

## (9) Spanish
Good accents and register. Minor: banner says «Autorizar de nuevo» "en Datos → Buzón" while API step 1 says "en esta pantalla" (dev noted it; banner clarifies it).

## (10) Accessibility
Real `<button>`s; states are text, not colour-only; `title` on the disabled sync button. Minor (N4): no `:disabled` style, so disabled buttons look almost enabled in the screenshots (not-configured and running states).

## Non-blocking findings
- **N1 (fix before manual check): step order.** `index.html:276-277` — `2. Escribe el nombre de la etiqueta… y guárdala.` / `3. Pulsa Autorizar…`. `PUT /api/mailbox/folder` calls `get_mail_source().resolve_folder` (`main.py:536`), which needs a token (`oauth.py:262` `AuthRevoked("no refresh token stored")` → 409). A user following the on-screen order gets «El permiso fue revocado: vuelve a autorizar.» (`index.html` L367, 409 branch) on a mailbox that was never authorised, which is misleading, and contradicts mail-source.md setup order (authorise → account shown → label). Fix: swap steps 2/3 and/or show "Autoriza primero" when `auth_state==='not_configured'` instead of "revocado".
- **N2: double-click on Autorizar.** `index.html:361` `$('#mbauth').onclick=async()=>{if(authWait)return;authMsg='';const r=await mbxCall('/authorise','POST');…authWait={…}` — `authWait` is set only after the response, so a quick double click sends two POSTs (two authorise threads/browser windows). Fix: set a `authStarting` flag/disable the button before the `await`.
- **N3: auth wait can outlive 5 minutes / end early.** (a) The timeout check sits inside `if(authWait&&mbx)` (L338); if `/api/mailbox` keeps failing, `mbx` is null, `authWait` never expires and the 2 s fast poll runs forever. (b) `authWait.state` is `mbx?mbx.auth_state:null`; if clicked while `mbx` is null, the first successful refresh sees `state!==null` and reports "El estado del buzón cambió". (c) Re-authorising while already `valid` produces no state/error change, so the UI waits 5 min and then says "Se agotó el tiempo" even if it succeeded. Edge cases, honest enough, worth a small fix.
- **N4: disabled styling** (no `button.b:disabled` rule) and ranking is not re-rendered if a sync finishes between two polls (`was` false, so the `renderRanking()` at L343 is skipped); the OOD banner still updates.

## Gates
Not part of this review (dev reports them). `git status` clean apart from this file.
