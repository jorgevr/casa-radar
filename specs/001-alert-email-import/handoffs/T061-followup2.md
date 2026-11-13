# T061 follow-up 2 — refresh mailbox status on focus; explicit click when revoked / not configured

File changed: `app/static/index.html` only.

## Bug
After re-authorising from the terminal (another process), returning to the tab left the page on the stale
"revoked" state (poll every 60 s, skipped while hidden, no focus handler) and the sync button was `disabled`
without any disabled look, so a click did nothing until F5.

## Changes
- `visibilitychange` (when visible) and window `focus` call `mbxOnReturn()` → `mbxRefresh()` (reuses `mbxSeq`
  guard and timers). Debounced 1 s (`mbxFocusAt`) so one return = one request.
- Sync button: real `disabled` only while `running || syncBusy || syncChecking`. For `revoked` / `not_configured`
  it uses `aria-disabled="true"` (plus the existing title tooltips) so the click runs.
- `syncNow`: in those states it first refreshes the status (`syncChecking` guards double clicks). If now valid
  it continues with the normal `POST /api/mailbox/sync`; if still revoked it shows
  «El permiso sigue revocado: usa «Autorizar de nuevo» en Datos → Buzón.»; if not_configured
  «Configura primero el buzón en Datos → Buzón.» (in the status bar, via `esc()`, cleared once the state is valid).
- CSS: `button.b:disabled, button.b[aria-disabled="true"]{opacity:.5;cursor:not-allowed}` (also the button-look part of N4).
- N2, N3 and the ranking re-render item of N4 untouched.

## Verified
- `node --check` on the inline JS: OK.
- RENDERED in headless Edge against an isolated server (temp CASA_DB/NEEDS/APPDATA under `%TEMP%\casa-agent-T061-g\ui`,
  port 18765, seeded revoked via `alerts_sync.write_state`): revoked page shows banner, button faded with
  `aria-disabled=true` and not `disabled`; clicking it re-queried the status (1 request) and showed the Spanish
  "sigue revocado" message (screenshot inspected); after changing the temp DB row to `valid`, dispatching
  `focus` + `visibilitychange` produced exactly one extra `/api/mailbox` request, state became valid, button
  lost aria-disabled, banner and note disappeared. Server and Edge stopped afterwards.
- NOT exercised (only read): the not_configured message, the valid-after-click path continuing to
  `POST /api/mailbox/sync` (would contact Gmail), real tab switching (events were dispatched synthetically).

## Gates
- compileall: OK
- pytest -m "not slow": 597 passed, 1 skipped, 2 deselected (isolated temp env)
- anonymise_eml --check: exit 0
- `git diff --name-only main...HEAD`: nothing forbidden; requirements.txt diff empty
