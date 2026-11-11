# T057 follow-up review

**[PASS]**

## Checks
- Only files touched: `app/mailbox/gmail.py`, `tests/test_mailbox_gmail.py`, `handoffs/T057-followup.md` (git diff --name-only). OK.
- Code: only change is `app/mailbox/gmail.py:42-43`: `if status in (401, 403): raise AuthRevoked(f"GET {path} status {status}")`. Message is method/path/status only; no token. The `!= 200 -> SourceUnavailable` line is untouched, so 404/429/5xx unchanged.
- No existing lines removed or loosened: `git diff ... -- tests/test_mailbox_gmail.py` has 0 deleted lines (pure append, +56).
- New tests (assertions quoted):
  - `test_401_403_raise_auth_revoked_without_token[401|403]`: `pytest.raises(AuthRevoked)`, `assert str(status) in text`, `assert "users/me/profile" in text`, `assert FAKE_TOKEN not in text`, `assert "Bearer" not in text`, `assert FAKE_TOKEN not in caplog.text`. Matches name. The 403 case fails on the old code (SourceUnavailable is not AuthRevoked).
  - `test_auth_revoked_on_every_call_path[401|403]`: resolve_folder, list_ids, fetch_raw each `pytest.raises(AuthRevoked)`. Good.
  - `test_resolve_folder_unknown_label_raises_folder_not_found`: 200 with labels `Alerts`, asks for `"Nope"`, `pytest.raises(FolderNotFound)`. Matches.
  - `test_404_is_source_unavailable_contract_lists_no_404`: `pytest.raises(SourceUnavailable)`, `"404" in str(...)`, `FAKE_TOKEN not in str(...)`. Matches.
- No real network: all use `httpx.MockTransport` via `_make_source` and the `no_network` fixture. Only fake token `FAKE_TOKEN = "fake-access-token-for-tests"` (tests/test_mailbox_gmail.py:25).
- Gates: `compileall` OK; `tests/test_mailbox_gmail.py` 17 passed. The full `-m "not slow"` suite exceeded 120s in my session and I did not wait for it (not confirmed by me).
- Handoff matches the diff. Red phase claim (only the two 403 cases failed) is consistent with the code diff; I did not re-run the old code (read-only).

## Minor notes (non-blocking)
- `assert FAKE_TOKEN not in caplog.text` is weak: `gmail.py` has no logging calls, so it can't fail today. Still a valid regression guard.
- The 401 cases pass before and after the change (expected; they are regression tests).
- Contract doc `contracts/mail-source.md` should be updated to "401 or 403" as the handoff proposes (user decision; not done here).
