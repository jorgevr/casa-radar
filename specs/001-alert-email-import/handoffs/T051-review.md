STATUS: [PASS]

Re-review (iteration 1) of `tests/test_mailbox_oauth.py` at commit a15d754. Diff main...HEAD touches only that file and `handoffs/T051-tests.md`. Previous review overwritten; handoff not trusted.

## Run (offline, CASA_* under %TEMP%\casa-review-T051)
`python -m pytest tests/test_mailbox_oauth.py -q` -> `7 failed in 0.32s`. Every failure is `E ModuleNotFoundError: No module named 'app.mailbox'` at the in-test imports (:60, :90, :126, :157, :174, :194, :216). Accepted failure reason; no syntax, fixture or other import errors.

## Previous required changes
1. Tautology removed: the old `parsed.hostname in {...} or ...` is gone. RESOLVED.
2. Bare `pytest.raises(Exception)` removed: :233 `pytest.raises((AuthRevoked, SourceUnavailable))` for the exchange 401, :250 `pytest.raises(AuthRevoked)` for refresh 401. RESOLVED for refresh; exchange 401 is a two-type accept (see open decision A).
3. Exception chain scanned: `_assert_exception_has_no_tokens` (:43-53) checks `str`, `repr`, `__cause__`, `__context__`; used at :246, :261. RESOLVED. Caplog scanned at :247, :262.
4. `prompt=consent`: :76 `assert qs.get("prompt") == ["consent"]`. RESOLVED (contract mail-source.md:43).
5. New tests: `test_exchange_code_invalid_grant_raises_auth_revoked` (:173-189, `pytest.raises(AuthRevoked)`) and `test_refresh_401_raises_auth_revoked` (:192-207). RESOLVED.
6. Invented names disclosed in handoff; listed below as open decisions.

## Behaviour coverage (task text -> test)
- scope only gmail.readonly: :73 `qs.get("scope") == [SCOPE]`, :83
- S256: :74; offline: :75; loopback redirect: :77, :79-81
- code exchange POST to token endpoint: :116-119 (`str(req.url) == TOKEN_URL`)
- refresh POST to token endpoint: :149-152
- `invalid_grant` -> `AuthRevoked`: :164 (refresh), :181 (exchange)
- errors method/path/status only, never tokens, caplog + exception text: :243-247, :258-262
No behaviour MISSING.

## Minor notes (non-blocking)
- :85-86 filler `assert parsed.scheme in {"https", "http"}` is near-vacuous; the comment ("Silence linter-style unused warning") is not a real purpose. Suggest deleting; does not make the test wrong.
- :243-245 and :258-260 check that "POST", "/token", "401" appear in `str(exc)` — this is an inclusion check, not proof that nothing else is included; acceptable since the secret scan covers the leak vector.
- POST tests (:116-122, :149-153) do not assert request body (`grant_type`, `code_verifier`, `refresh_token`); not required by task text.
- :31-40 `FAKE_ROTATED_REFRESH_TOKEN` is never returned by any mock, so its scan is inert; harmless.
- Scope/offline/constitution: PASS. All tests use `no_network` (conftest.py:51-56) + `httpx.MockTransport`; only `FAKE_*` strings; no app/, conftest, requirements, config, data or `.eml` changes; no rate/threshold literals.

## Open decisions for the user (interfaces pinned by the tests that tasks.md/contracts do not state)
A. Exception type for a 401 on the code exchange: tests accept `AuthRevoked` or `SourceUnavailable` (:233). Docs only name `AuthRevoked` for 401 after refresh. Pick one so the test can be narrowed.
B. Function names/signatures: `build_authorization_url(client_id, redirect_uri, state, code_challenge)` (:60-68), `exchange_code(client_id, client_secret, code, redirect_uri, code_verifier, transport=)` (:107-113), `refresh_access_token(client_id, client_secret, refresh_token, transport=)` (:142-147). T056 names only `authorize()` and `access_token()`.
C. `transport=` keyword for injecting `httpx.MockTransport` into these helpers.
D. Dict-style results: `result["access_token"]`, `result["refresh_token"]` (:121-122, :153) instead of an object/Secret holder (R4 asks for a redacted `Secret`; a `Secret` would break `result["..."] == str`).
E. `AuthRevoked` and `SourceUnavailable` importable from `app.mailbox` (consistent with T054).
