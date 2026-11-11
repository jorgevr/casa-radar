# T056 review

**Verdict: [PASS]** (two non-blocking findings, see F1 and F2; both fail safe and neither leaks a secret)

Reviewed `git diff jorgevr/Implementation...HEAD` (only `app/mailbox/oauth.py` and the dev handoff) and the full file.
I also exercised `_wait_for_redirect` on a local loopback socket (no Google, no browser, CASA_* pointed at `%TEMP%\casa-agent`).

## Checklist

- [OK] State generated and verified: `app/mailbox/oauth.py:175` `state = secrets.token_urlsafe(24)`; checked at `:193` `if not secrets.compare_digest(params.get("state", ""), state):` before the code is exchanged. Constant-time compare.
- [OK] Verifier: `:41` `_b64url(secrets.token_bytes(48))` gives 64 chars (RFC 7636 range 43-128), 384 bits from `secrets`. Challenge `:45` is S256 over `hashlib.sha256`, unpadded base64url; `code_challenge_method` `"S256"` at `:56`.
- [OK] Loopback bind: `:176` `HTTPServer(("127.0.0.1", 0), BaseHTTPRequestHandler)`. Not `localhost`, not `0.0.0.0`; redirect URI built from the actual port at `:178`.
- [OK] Server shutdown: `:187-188` `finally: server.server_close()` covers browser-open and wait failures. Single-threaded, `handle_request` loop, so no leftover thread.
- [OK] Timeout default: `:26` 300 s, passed at `:167`; empty result raises `TimeoutError` (`:189-190`). Measured: with no request, `_wait_for_redirect(s, 1.0)` returned `{}` after 1.0 s.
- [OK] No secrets in logs/exceptions: `:150-151` `def log_message(...): return` suppresses the request line (it carries the code). Messages are built from `_failure` `:64` `f"POST {_TOKEN_PATH} returned {status}"` and the exception class name `:73`; all raised `from None`. `PermissionError(f"authorisation refused: {params['error']}")` `:192` echoes the `error` query value, which is not a secret (see F3). Handoff contains no tokens.
- [OK] Scope: `:23` `SCOPE = "https://www.googleapis.com/auth/gmail.readonly"`, the only scope, used only at `:53`.
- [OK] HTTP targets: `httpx` only at `:70-71` `client.post(TOKEN_URL, data=data)`, `TOKEN_URL = "https://oauth2.googleapis.com/token"` (`:25`); the auth URL is only built and handed to the browser (`:60`, `:185`). `follow_redirects` is left at httpx's default (off). Timeout 30 s.
- [OK] No new dependency: `git diff jorgevr/Implementation...HEAD -- requirements.txt` is empty. Imports are stdlib plus `httpx`.
- [OK] Scope of change: only `app/mailbox/oauth.py` (+ the dev handoff). No hot file touched.
- [OK] Persistence: `_cache` (`:33`) is memory only; the refresh token is written only via `save_refresh_token(Secret(...))` at `:206` and `:243`. `Secret` wraps it, so nothing prints it. Refresh-token rotation is handled (`:241-243`).
- [OK] AuthRevoked mapping: `:89` `if error == "invalid_grant" or (status == 401 and revoke_on_401):` gives AuthRevoked for refresh (401 or invalid_grant); a 401 on exchange gives SourceUnavailable, matching decisions.md T056.
- [OK] No imputed values: a missing refresh token raises (`:204-205`), a missing stored token raises AuthRevoked (`:232-233`). Endpoints, scope and timeouts are named constants. `expires_in` that is absent or malformed gives lifetime 0 (`:213-215`), so the token is not cached and is refreshed again; this fails safe.

## Findings (non-blocking)

- **F1 [minor] The 5-minute timeout is not strictly enforced against an idle local connection.**
  `:159-160` `server.timeout = remaining` / `server.handle_request()` only bounds waiting for `accept`. The accepted connection's handler has no socket timeout (`BaseHTTPRequestHandler.timeout` is None), so a client that connects to the port and sends nothing blocks `handle_request`. I reproduced it: with a 1 s timeout and one idle connection, the thread was still alive after 4 s. Only a local process could do this, and the user's own flow is unaffected. Suggested fix, in a follow-up: set `timeout = remaining` on the `Handler` class (it is read as the per-connection socket timeout).
- **F2 [minor] A wrong-state callback ends the wait instead of being ignored.**
  `:138-139` `if "code" in query or "error" in query: result.update(query)` accepts the first request carrying `code` or `error`, and the state is checked only afterwards (`:193`). Reproduced: `/?code=A&state=BAD` followed by `/?code=B&state=OK` returned `{'code': 'A', 'state': 'BAD'}`, so `authorize()` raises `PermissionError`. It fails closed (no token is obtained and the CSRF code is never exchanged), but any local process that guesses the port can abort the user's authorisation. This matches "only the first matching callback accepted" as the review brief states it. Optionally check `state` inside the handler and keep waiting on a mismatch.
- **F3 [nit] `:192` `raise PermissionError(f"authorisation refused: {params['error']}")`** puts an unsanitised query value into an exception message (an arbitrary local request can set it). The expected values are short codes such as `access_denied`. Not a secret; consider an allow-list or truncation.
- **F4 [nit] `:185` `open_browser(url)` return value is ignored.** If no browser can be opened (`webbrowser.open` returns False), the user waits the full 5 minutes before a `TimeoutError`.

## Tests and gates

- `authorize()` and the loopback server have no tests (as the dev handoff states); they were reviewed by reading and by the socket experiment above.
- Gates (CASA_* pointed at `%TEMP%\casa-agent`): compileall passed. `pytest -m "not slow"`: 510 passed, 22 failed, 1 skipped. All 22 failures are in `tests/test_mailbox_gmail.py` (11, T057) and `tests/test_sync.py` (11, T058; e.g. `ImportError: cannot import name 'alerts_sync' from 'app'`): tests written ahead of tasks not yet implemented, none touch `oauth.py`. `tests/test_mailbox_oauth.py` + `tests/test_mailbox_credentials.py`: 11 passed. The anonymise check printed no failure (its output was cut by my `tail`, so I did not capture an explicit OK line). `git diff --name-only` lists no `data/`, config, secret or `.eml` paths; `requirements.txt` diff is empty.
