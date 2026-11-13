# T056 dev handoff

## What changed
- New `app/mailbox/oauth.py` (only file touched besides this handoff).
- Public: `SCOPE` (gmail.readonly only), `build_authorization_url(*, client_id, redirect_uri, state, code_challenge)`,
  `exchange_code(*, ..., transport=None)`, `refresh_access_token(*, ..., transport=None)` (dict results),
  `authorize(*, open_browser=webbrowser.open, timeout=300, transport=None)`, `access_token(*, transport=None)`, `clear_cache()`.
- PKCE S256 via `secrets`/`hashlib`; loopback `http.server` on `127.0.0.1:0`; state checked; request log suppressed (it would carry the code).
- `access_token()` caches in memory only, with a 60 s margin; saves a rotated refresh token if Google returns one.
- Errors: message is `POST /token returned <status>` (or exception class name for network errors), raised `from None`.
  - refresh: 401 or 400 `invalid_grant` -> `AuthRevoked`; other statuses/network -> `SourceUnavailable`.
  - exchange: 400 `invalid_grant` -> `AuthRevoked` (test requires it); 401 -> `SourceUnavailable` (decisions.md).

## Decisions not covered by docs
- Signatures of `authorize()` / `access_token()` are mine (tests do not call them); `open_browser` and `transport` are injectable for later tests.
- Token URL is the `TOKEN_URL` constant (tests assert it), not `token_uri` from client_secret.json.
- `authorize()` raises `TimeoutError` (no redirect in 5 min) and `PermissionError` (user refusal / state mismatch); a missing refresh token raises `SourceUnavailable`. The CLI task (mailbox-setup) should translate these.
- No stored refresh token in `access_token()` -> `AuthRevoked("run mailbox-setup")`.
- No test contradicts decisions.md.

## Reviewer should check
- No token/secret/code reaches messages, logs (httpx logs URL only) or the cache beyond memory.
- `authorize()` and the loopback server are untested (no tests exist; need browser/socket); exercised by reading only.

## Gates
- compileall: pass. `tests/test_mailbox_oauth.py` + `test_mailbox_credentials.py`: 11 passed.
- Full `pytest -m "not slow"`: see report (run in background; slow to finish).
- anonymise check, forbidden-path diff, requirements diff: see report.
