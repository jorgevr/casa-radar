# T051 tests handoff

## Task
T051 [P] [US1] Add `tests/test_mailbox_oauth.py` (Phase 9 mailbox sync, tests-first). Implementation `app/mailbox/oauth.py` and `app/mailbox/__init__.py` (errors like `AuthRevoked`) are out of scope and do not exist yet.

## Files changed
- `tests/test_mailbox_oauth.py`: OAuth/mailbox auth tests (updated in review iteration 1).
- `specs/001-alert-email-import/handoffs/T051-tests.md` (this handoff).

## What each test asserts
All tests are offline (`no_network` fixture) and use `httpx.MockTransport` only; no Google/browser/real sync. Token-like strings are obviously fake (`FAKE_*`).

1. `test_authorize_url_has_only_gmail_readonly_scope_pkce_s256_offline_loopback_redirect_and_prompt_consent`
   - Calls `app.mailbox.oauth.build_authorization_url(client_id, redirect_uri, state, code_challenge)` with loopback `redirect_uri="http://127.0.0.1:43123/"`.
   - Asserts parsed query contains only scope `https://www.googleapis.com/auth/gmail.readonly`, `code_challenge_method=S256`, `access_type=offline`, `prompt=consent` (contracts/mail-source.md authorisation step 2), and the provided loopback `redirect_uri` (http, host `127.0.0.1`).
   - Asserts no extra scope tokens and no fake token leakage in the URL.

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
   - Asserts `refresh_access_token(...)` raises `app.mailbox.AuthRevoked`.

5. `test_exchange_code_invalid_grant_raises_auth_revoked`
   - Mocks token endpoint returning `400 {"error":"invalid_grant"}`.
   - Asserts `exchange_code(...)` raises `app.mailbox.AuthRevoked`.

6. `test_refresh_401_raises_auth_revoked`
   - Mocks token endpoint returning `401`.
   - Asserts `refresh_access_token(...)` raises `app.mailbox.AuthRevoked` (mail-source contract: 401 after refresh -> AuthRevoked).

7. `test_token_endpoint_errors_expose_method_path_status_only_and_never_tokens`
   - Mocks token endpoint returning `401` with a body that echoes fake client secret/code/refresh/access/verifier.
   - For `exchange_code`: asserts `pytest.raises((AuthRevoked, SourceUnavailable))` because the contracts/task do not name a specific error type for code-exchange 401; accepting either is recorded as an **open decision** pending coordinator/user approval before T056. The exception text must contain `POST`, `/token`, `401`, and no fake token/secret strings may appear in `str/repr(excinfo.value)`, exception chain (`__cause__`/`__context__` str/repr), or `caplog.text`.
   - For `refresh_access_token`: asserts `pytest.raises(AuthRevoked)` (contract-named for 401 after refresh) with the same method/path/status-only and no-token checks including `repr`, exception chain, and `caplog`.

## Decisions / assumptions (docs do not fully spell out names)
- **NEW proposed names/shapes, pending approval by the user before T056 is dispatched (recorded per review):** `app.mailbox.oauth.build_authorization_url(client_id, redirect_uri, state, code_challenge)`, `exchange_code(client_id, client_secret, code, redirect_uri, code_verifier, transport=None)`, `refresh_access_token(client_id, client_secret, refresh_token, transport=None)`, and dict-style results (`result["access_token"]`, `result["refresh_token"]`). These are not in tasks.md/contracts (T056 names `authorize()`/`access_token()`); they are proposed for MockTransport-injectable, browser-free unit tests consistent with R2/R3 behavior. Coordinator/user must confirm/adjust before implementation binds to them.
- `AuthRevoked` and `SourceUnavailable` are imported from `app.mailbox` as per mail-source contract/T054.
- `prompt=consent` is asserted in the authorize URL per contracts/mail-source.md authorisation flow step 2 (needed for offline refresh tokens); task text did not list it explicitly but it is required by the contract.
- Open decision (to be resolved by coordinator/user): specific exception type for **code-exchange 401** when not `invalid_grant`; test currently accepts `(AuthRevoked, SourceUnavailable)` and records this.

## Review iteration 1 changes (addressed T051-review.md)
1. Removed tautological authorize-URL assertion.
2. Replaced bare `pytest.raises(Exception)` with specific types: refresh 401 -> `AuthRevoked`; exchange 401 -> `(AuthRevoked, SourceUnavailable)` with open-decision note.
3. Token-leak scan now covers `str(excinfo.value)`, `repr(excinfo.value)`, and exception chain `__cause__`/`__context__` (str/repr) in addition to `caplog`.
4. Added `prompt=consent` assertion in authorize URL.
5. Added `test_refresh_401_raises_auth_revoked` and `test_exchange_code_invalid_grant_raises_auth_revoked`.
6. Recorded proposed helper names and dict result shape as needing coordinator/user approval before T056.

Optional request-body assertions were not added.

## Reviewer notes
- Each test does in-function imports so collection succeeds and each test fails individually on the missing module (see observed failures).
- No `app/` code, no stubs, no `tests/conftest.py`/deps/config/data/tasks.md changes, no secrets.
- Gates run with isolation env `CASA_DB/NEEDS/APPDATA` under `$env:TEMP\casa-agent-T051`.

## Observed failures (right reason)
Command: `python -m pytest tests/test_mailbox_oauth.py -q` (worktree root, isolated env set)
Result: **7 failed in 0.61s**. All failures are `ModuleNotFoundError: No module named 'app.mailbox'` raised at in-test imports:
- `test_authorize_url_has_only_gmail_readonly_scope_pkce_s256_offline_loopback_redirect_and_prompt_consent` -> `from app.mailbox.oauth import build_authorization_url`
- `test_exchange_code_posts_to_token_endpoint` -> `from app.mailbox.oauth import exchange_code`
- `test_refresh_posts_to_token_endpoint` -> `from app.mailbox.oauth import refresh_access_token`
- `test_refresh_invalid_grant_raises_auth_revoked` -> `from app.mailbox import AuthRevoked`
- `test_exchange_code_invalid_grant_raises_auth_revoked` -> `from app.mailbox import AuthRevoked`
- `test_refresh_401_raises_auth_revoked` -> `from app.mailbox import AuthRevoked`
- `test_token_endpoint_errors_expose_method_path_status_only_and_never_tokens` -> `from app.mailbox import AuthRevoked, SourceUnavailable`

This is the accepted "missing module (app.mailbox)" failure for Phase 9 tests-first (no stubs created).
