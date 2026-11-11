# T057 follow-up (Gmail 403 -> AuthRevoked)

## Changed
- `app/mailbox/gmail.py`: HTTP 403 now raises `AuthRevoked` like 401 (message: `GET <path> status <code>`, no token).
  All other mappings unchanged (429/5xx/timeout/transport/other non-200 -> `SourceUnavailable`).
- `tests/test_mailbox_gmail.py` (new tests only; none existing touched):
  - `test_401_403_raise_auth_revoked_without_token[401|403]` (also asserts no fake token / "Bearer" in text or caplog)
  - `test_auth_revoked_on_every_call_path[401|403]`
  - `test_resolve_folder_unknown_label_raises_folder_not_found`
  - `test_404_is_source_unavailable_contract_lists_no_404`

## Decisions not covered by docs
- `contracts/mail-source.md` has no 404 row, so 404 stays `SourceUnavailable`.
- Proposed doc change: contracts/mail-source.md AuthRevoked row should say "401 or 403 after refresh".

## Red phase
Before the code change, only the two 403 cases failed (SourceUnavailable instead of AuthRevoked).
