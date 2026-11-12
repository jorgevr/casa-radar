# T061 follow-up review (finding N1 only) — [PASS]

Scope: `git diff jorgevr/Implementation...HEAD` (app/static/index.html +6/-6, plus dev handoff). N2–N4 ignored by design.
Method: code read + `new Function` syntax check of the inline script (OK). Nothing rendered by me; all states below were only read (the dev's handoff claims renders of not_configured/valid/revoked; I did not reproduce them). No server run, no real data touched.

## Findings (all OK)
1. Step text/numbering — app/static/index.html:275-277: `2. Pulsa Autorizar: …` then `3. Escribe el nombre de la etiqueta …`; step 1 unchanged. DOM order matches (Autorizar/Desconectar row :280 above label row :281). No other text refers to step numbers; banner (:329) says «Autorizar de nuevo» in Datos → Buzón, no numbering. OK.
2. Disabled state — :357 `const ncs=!!mbx&&mbx.auth_state==='not_configured';$('#mbsave').disabled=folderBusy||ncs;$('#mbhint').textContent=ncs?'Autoriza primero el buzón':'';` Hint is neutral, no «revocado». Enter key: the input `#mbl` (:281) is not inside a `<form>`, and the file has no keydown/keypress/onsubmit handler (grep), so Enter cannot trigger the save; the only call site is `$('#mbsave').onclick` (:364-366), and a disabled button does not fire click. OK.
3. Re-enable without reload — drawMbc (:352-358) is called from drawMbx (:315, :328), which mbxRefresh calls each poll (:342); polling is fast while authWait is set (:332). When state becomes valid, `ncs` is false → button enabled, hint cleared. OK (read only).
4. 409 branch — :367 `r.status===409?(mbx&&mbx.auth_state==='revoked'?'El permiso fue revocado: vuelve a autorizar.':'Autoriza primero el buzón.')`. revoked → «revocado» wording; not_configured, valid, null/unknown (mbx null → falsy) → neutral message. OK. Other status branches unchanged.
5. Escaping — 409 text goes through `esc(t)` (:368); hint set via `textContent` (:357); both are constants anyway. OK.
6. Removed lines — all 6 removed lines inspected: 2 step texts (swapped), the label row (re-added with margin-top:10px and hint span), the Autorizar row (re-added with margin-top:0), `disabled=folderBusy` (extended), the 409 string (extended). No behaviour lost. IDs `mbl/mbsave/mbauth/mbdis/mbmsg` unchanged. No external refs, no dependency, requirements.txt untouched.

## Non-blocking observations (not failures)
- When mbx is null (status fetch failed, :315/:337) `ncs` is false, so the save button is enabled; a click then hits the endpoint and a 409 shows the neutral message. Acceptable; spec only requires disabling for 'not_configured'.
- Stale `mbx` between polls: the 409 wording uses the last polled state; fine.
