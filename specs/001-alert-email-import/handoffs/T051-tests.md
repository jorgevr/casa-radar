# T051 tests handoff

## Task
T051 [P] [US1] Add `tests/test_mailbox_oauth.py` (Phase 9 mailbox sync, tests-first). Implementation `app/mailbox/oauth.py` and `app/mailbox/__init__.py` (errors like `AuthRevoked`) are out of scope and do not exist yet.

## Files changed
- `tests/test_mailbox_oauth.py` (new): OAuth/mailbox auth tests.
- `specs/001-alert-email-import/handoffs/T051-tests.md` (this handoff).

## What each test asserts
All tests are offline (`no_network` fixture) and use `httpx.MockTransport` only; no Google/browser/real sync. Token-like strings are obviously fake (`FAKE_*`).

1. `test_authorize_url_has_only_gmail_readonly_scope_pkce_s256_offline_and_loopback_redirect`
   - Calls `app.mailbox.oauth.build_authorization_url(client_id, redirect_uri, state, code_challenge)` with loopback `redirect_uri="http://127.0.0.1:43123/"`.
   - Asserts parsed query contains only scope `https://www.googleapis.com/auth/gmail.readonly`, `code_challenge_method=S256`, `access_type=offline`, and the provided loopback `redirect_uri` (http, host `127.0.0.1`).

2. `test_exchange_code_posts_to_token_endpoint`
   - Calls `app.mailbox.oauth.exchange_code(..., transport=MockTransport)`.
   - Asserts exactly one recorded request: `POST https://oauth2.googleapis.com/token`.
   - Asserts returned result includes access/refresh tokens from the mock response.

3. `test_refresh_posts_to_token_endpoint`
   - Calls `app.mailbox.oauth.refresh_access_token(..., transport=MockTransport)`.
   - Asserts exactly one recorded request: `POST https://oauth2.googleapis.com/token`.
   - Asserts returned access token from mock response.

4. `test_refresh_invalid_grant_raises_auth_revoked`
   - Mocks token endpoint returning `400 {"error":"invalid_grant"}`.
   - Asserts `refresh_access_token(...)` raises `app.mailbox.AuthRevoked` (per mail-source contract mapping).

5. `test_token_endpoint_errors_expose_method_path_status_only_and_never_tokens`
   - Mocks token endpoint returning `401` with a body that echoes fake client secret/code/refresh/access/verifier.
   - For both `exchange_code` and `refresh_access_token` (separately, with `caplog` cleared): asserts exception is raised, exception text contains method `POST`, path `/token`, and status `401`, and that none of the fake token/secret strings appear in exception text or `caplog.text`.

## Decisions / assumptions (docs do not fully spell out names)
- Assumed OAuth helper API names and signatures for testability: `build_authorization_url(client_id, redirect_uri, state, code_challenge)`, `exchange_code(client_id, client_secret, code, redirect_uri, code_verifier, transport=None)`, `refresh_access_token(client_id, client_secret, refresh_token, transport=None)`. These are reasonable given R2/R3/T056 ("authorise URL", code exchange/refresh POSTs) and allow `httpx.MockTransport` injection without browser/loopback side effects; implementer can satisfy or adapt interface to match behavior required by contracts.
- `AuthRevoked` is imported from `app.mailbox` as per mail-source contract/T054.
- Error-safety test asserts `POST`, `/token`, `401` present and fake secrets absent (method/path/status only requirement); it does not over-constrain exact exception type beyond "Exception" for non-`invalid_grant` errors.

## Reviewer notes
- Each test does in-function imports so collection succeeds and each test fails individually on the missing module (see observed failures).
- No `app/` code, no stubs, no `tests/conftest.py`/deps/config/data/tasks.md changes, no secrets.
- Gates run with isolation env `CASA_DB/NEEDS/APPDATA` under `$env:TEMP\casa-agent-T051`.

## Observed failures (right reason)
Command: `python -m pytest tests/test_mailbox_oauth.py -q` (worktree root, isolated env set)
Result: `5 failed in 48.46s`.
All failures are `ModuleNotFoundError: No module named 'app.mailbox'` raised at the in-test imports:
- `test_authorize_url_has_only_gmail_readonly_scope_pkce_s256_offline_and_loopback_redirect` -> `from app.mailbox.oauth import build_authorization_url`
- `test_exchange_code_posts_to_token_endpoint` -> `from app.mailbox.oauth import exchange_code`
- `test_refresh_posts_to_token_endpoint` -> `from app.mailbox.oauth import refresh_access_token`
- `test_refresh_invalid_grant_raises_auth_revoked` -> `from app.mailbox import AuthRevoked`
- `test_token_endpoint_errors_expose_method_path_status_only_and_never_tokens` -> `from app.mailbox.oauth import exchange_code, refresh_access_token`

This is the accepted "missing module (app.mailbox)" failure for Phase 9 tests-first (no stubs created).
