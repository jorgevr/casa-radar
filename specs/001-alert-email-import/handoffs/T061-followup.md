# T061 follow-up (finding N1) — dev handoff

File changed: `app/static/index.html` only.

## What changed
- Buzón card steps reordered: 1 client_secret.json, 2 Autorizar, 3 label. DOM order matches: the Autorizar/Desconectar row now sits above the label row.
- When `auth_state === 'not_configured'`, "Guardar etiqueta" is disabled and a hint "Autoriza primero el buzón" is shown beside it (new `#mbhint` span; no endpoint call possible).
- 409 on the label save: "El permiso fue revocado: vuelve a autorizar." only if `auth_state === 'revoked'`; otherwise "Autoriza primero el buzón.". Message still goes through `esc()`.
- N2, N3, N4 untouched. No restyle, no new dependency.

## Verification
- `node --check` on the inline script: OK.
- Rendered with headless Edge against a temp server (CASA_DB/CASA_NEEDS/CASA_APPDATA under `%TEMP%\casa-agent-T061-fu`, port 8791, fake account demo@example.test), mailbox_state row inserted/updated in the temp DB. States rendered: not_configured (button disabled with hint, text order OK), valid (button enabled, no hint), revoked (button enabled, no hint, "Autorizar de nuevo"). The 409 branch was not exercised live (would need a real call); verified by reading. Autorizar/Sincronizar were never clicked. Server stopped; the temporary default-tab edit used for screenshots was reverted.
- Note: `write_state` only UPDATEs, so seeding needed an INSERT of row id=1 first.

## Gates
compileall OK; pytest -m "not slow": 597 passed, 1 skipped, 2 deselected; anonymise --check rc=0; forbidden-path diff empty; requirements.txt diff empty.
