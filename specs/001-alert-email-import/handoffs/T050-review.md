STATUS: [PASS]

Re-review of commit 176a766 (iteration 1). Independent read of `tests/test_mailbox_credentials.py` (95 lines) vs tasks.md T050/T055, research R4. Previous review overwritten. pytest not run; failure reason derived from code (`_credentials()`, line 24, is the first statement that touches the implementation in every test, incl. before the `raises` at line 83) → `ModuleNotFoundError: No module named 'app.mailbox'`, the accepted reason.

PASS is conditional on the user acknowledging the OPEN DECISIONS below (they are not in tasks.md/contracts/research); the tests are otherwise sound.

## Previous required changes

1. Deterministic accessor (F1): RESOLVED. Lines 39-40: `assert not isinstance(loaded, str)` / `assert loaded.value == FAKE_TOKEN`; the probing of str/get_secret_value/secret is gone. (But see OD1.)
2. Consistency tests 1 vs 3 (F2): RESOLVED. Both forbid `str` (lines 39, 66) and use `.value` (40, 67).
3. Dead assertion (F3): RESOLVED. Line 71 `assert "refresh-token" not in rendered`; "refresh-token" really occurs in the token (line 20). Line 67 also now proves `.value` still works so the redaction check is not vacuous.
4. Over-broad raises (F4): RESOLVED. Line 83 `pytest.raises(ValueError, match=r"(?i)repository|repo|inside")` on the first operation `save_refresh_token` (84); inner try/except removed; line 86 `assert list(inside_repo.iterdir()) == []` checks nothing was written. (See OD2 and W1.)
5. `no_network` (F5): RESOLVED. Requested in all four tests (lines 29, 44, 58, 74); fixture exists at tests/conftest.py:51.

## OPEN DECISIONS for the user (pinned by tests, not stated in tasks.md/contracts)

- OD1. `Secret` exposes the token as a `.value` attribute (tests lines 40, 67; docstring 6-8). T055 only says "a `Secret` holder with redacted `__repr__`/`__str__`"; R4 says "one object whose `repr` is redacted". Accessor name is invented by the test author. Decide: keep `.value` (then add it to T055/data docs) or choose another (e.g. `reveal()`); also that `load_refresh_token()` returns the holder, not `str` (T055 does not say what it returns).
- OD2. Refusal of a repository-local `CASA_APPDATA` raises `ValueError` (line 83). T055 says only "refuse a path inside the repository"; the task text for T050 says "assert raises". Decide the exception type (ValueError vs a custom error, which would be a different base) and that the message mentions repository/repo/inside (match, line 83). Also that the check happens on `save_refresh_token` (the first operation), not only at import/load of the folder.
- OD3. `token.bin` under `CASA_APPDATA` (line 51): this IS stated in research R4 line 63 and T055 ("`token.bin`"), so not an invention; listed for completeness. No open decision.
- OD4. Probe directory name `.tmp-casa-appdata-inside-repo` created inside the worktree root (line 78): how T055 defines "repository root" (parent of `app/`? git root?) is unspecified; the test assumes `Path(__file__).parent.parent`, which matches both in this layout.

## Wrong-reason / weakness analysis

- W1 (minor, line 83): `match=r"(?i)repository|repo|inside"` is very permissive ("repo" subsumes "repository"; "inside" could match unrelated ValueErrors, e.g. an invalid-path message). Still far stronger than `Exception`, and the empty-directory assertion (86) ensures nothing was written. Non-blocking; could be tightened once T055 fixes the message.
- W2 (minor, lines 54-55): the DPAPI test only proves absence of UTF-8/UTF-16LE cleartext; it would also pass if `token.bin` held e.g. base64 or reversed text. Test 1 does not cover this either. Acceptable for the task wording ("do not contain the token in clear"); non-blocking.
- W3 (minor, line 43): the non-Windows branch (`token.json`, owner-only) is skipped/untested; the task only requires the Windows check. Fine.
- W4 (line 89-94): cleanup in `finally` no longer swallows errors; if `inside_repo.mkdir`/iterdir fails the test errors loudly (good). If the implementation wrongly writes there, the assertion at 86 fails and cleanup still removes it.
- No `assert True`, no skip/xfail except the allowed Windows skipif, no broad `except`.

## Checklist

1. Coverage: all four task behaviours covered — round-trip (test 1, 29-40), DPAPI bytes (44-55), repr redaction (58-71), repo-root refusal (74-94). None MISSING.
2. Assertion strength: OK (W1-W3 minor).
3. Offline: OK; `no_network` used; DPAPI writes only to `tmp_path`; only in-repo write is the probe dir, cleaned in `finally`. No Google/HTTP.
4. Failure reason: ModuleNotFoundError (see above); no syntax/fixture issue visible; `no_network` fixture exists.
5. Scope: `git diff main...HEAD --name-only` = `tests/test_mailbox_credentials.py` and `specs/001-alert-email-import/handoffs/T050-tests.md` only. Token is obviously fake (line 20). No secrets/PII/.eml.
6. Constitution: no imputed values, no rate/threshold literals; Art. III respected (redaction asserted, nothing written in repo); IV/V/VI untouched.
7. Spec fidelity: tests add no behaviour beyond the task except OD1/OD2; they omit `delete_token`/`load_client_secret` (not in T050 text; OK).

## Action requested

No test changes required. The coordinator should put OD1 and OD2 (and OD4 if desired) to the user before T055 is implemented, and record the decisions in tasks.md T055 / the handoff so the dev implements the same interface.
