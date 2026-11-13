# T061 follow-up 2 — review

Verdict: **[PASS]** (no blocking findings; four minor notes, none in scope to block)

Scope reviewed: `git diff jorgevr/Implementation...HEAD` (app/static/index.html + the dev handoff). Method: full diff read,
surrounding code read (mbxRefresh/mbxSchedule/drawMbx/syncNow). **Nothing was rendered by me**: every state below was
READ, not rendered (the dev handoff claims a render of revoked / revoked→valid; I did not reproduce it). Not read: data/, needs.yaml, appdata.

## 1. Visibility / focus handlers
- `index.html:386-387` `function mbxOnReturn(){if(document.hidden)return;const t=Date.now();if(t-mbxFocusAt<1000)return;mbxFocusAt=t;mbxRefresh()}` registered once at script top level (`document.addEventListener('visibilitychange',mbxOnReturn);window.addEventListener('focus',mbxOnReturn)`), not inside render()/drawMbx → no duplicate listeners after re-render. OK.
- Debounce is a 1 s timestamp, no timer → nothing to leak. visibilitychange+focus together = one request. OK.
- Reuses `mbxRefresh` (`:335` `const my=++mbxSeq` … `if(my!==mbxSeq)return`): an in-flight poll is superseded and its response dropped; mbxSchedule (`:333` `clearTimeout(mbxTimer)`) keeps a single timer. A return while a refresh is in flight issues one new request and drops the older answer (does not skip it) — acceptable, bounded to one per second. Sync running/syncBusy: no new guard needed; polls already run every 2 s then.
- Minor (M1): `mbxFocusAt` starts at 0, so a `focus` event firing on initial load adds one request next to the initial `mbxRefresh()` (`:389`); the seq guard drops the first. Harmless.

## 2. Click path (`syncNow`, :347-361)
- Guard `if(syncBusy||syncChecking||(mbx&&mbx.running))return` kept and extended. Button gets real `disabled` when `dis=run||syncBusy||syncChecking` (`:324`); `aria-disabled` only when `soft&&!dis` (`:327`). No double submit: syncChecking is set before the first await, syncBusy before the POST.
- valid: skips the re-check block, `mbxNote='';syncBusy=true;drawMbx();const r=await mbxCall('/sync','POST')` and the rest unchanged (diff shows no change below it). OK.
- revoked / not_configured: `syncChecking=true;...await mbxRefresh();syncChecking=false;` then the state after the re-check decides: `if(st==='revoked')mbxNote='El permiso sigue revocado: usa «Autorizar de nuevo» en Datos → Buzón.'` / `else if(st==='not_configured')mbxNote='Configura primero el buzón en Datos → Buzón.'`; `if(st!=='valid'){drawMbx();return}`; `if(mbx.running)return` (valid and already running → no POST). Messages are constants and shown through `esc(mbxNote)` (`:326`). Spanish text matches the request exactly.
- null/unknown auth_state with mbx present: not soft, not disabled → goes to POST as before (unchanged behaviour). mbx null (fetch error): button not rendered (`:322` early return), error text shown. If the re-check itself fails, st is undefined → `st!=='valid'` → drawMbx shows `mbxErr`, no silent failure.
- running/syncBusy: real disabled + guard.
- Keyboard: aria-disabled button keeps focus and Enter/Space fire click natively; screen readers announce it as dimmed/unavailable plus the `title`. OK.
- Minor (M2, a11y): `#mbx` (`:34`) has no `aria-live`/`role="status"`, and drawMbx replaces `el.innerHTML` (twice per click: syncChecking draw, then result draw), so keyboard focus drops to body and a screen reader will not announce the new note. Visual users are fine. Pre-existing pattern (polls already do this).
- Minor (M3): `mbxNote` is cleared only when state is `valid` (`:325`) or on the next click; a note "sigue revocado" can remain visible if the state later turns not_configured (e.g. after Desconectar) until the next click. Cosmetic.
- Minor (M4): if two refreshes race (focus refresh superseding the click's re-check), `await mbxRefresh()` returns without new data, so st is read from the previous mbx and the "sigue revocado" note may show for a moment; the newer response then redraws and clears the note when valid (`:325`). Self-heals.
- `syncChecking=false` is not in a try/finally; mbxRefresh cannot reject in practice (mbxCall catches), so low risk.

## 3. Style
- `:21` `button.b:disabled,button.b[aria-disabled="true"]{opacity:.5;cursor:not-allowed}` — covers both, scoped to `button.b`; enabled buttons are unchanged. Side effect: all other `button.b:disabled` (e.g. Reprocesar while busy, Autorizar while waiting) now also look faded — consistent with the request ("N4" button-look), not a regression.
- Dark theme (read from tokens `:9`): --ink #ecebe6 at 50% over --card #1f1f1c ≈ 5:1; legible. Light: ≈3:1, visibly dimmed yet readable (disabled-state contrast is exempt, though this one is actionable). `cursor:not-allowed` on a button that does react to click is slightly misleading; cosmetic.

## 4. Nothing else changed
All removed lines inspected: the CSS `button.b{cursor:pointer}` line (rule preserved + new rule), the `let …` declaration (3 vars added), `const dis=…` and the button template (replaced), `async function syncNow(){…syncBusy=true;drawMbx();` (replaced by the block above, same tail). No external URLs added (`grep https?://` finds none new), requirements.txt/other files untouched, only index.html + handoff. Only dynamic string added is `mbxNote`, escaped with `esc()`; the aria-disabled/disabled attributes are constants.
