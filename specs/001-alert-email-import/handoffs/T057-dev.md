# T057 dev handoff

## Changed
- New `app/mailbox/gmail.py`: `GmailSource(*, client, access_token)` implementing `MailSource`.
  - `account()` -> GET users/me/profile; `resolve_folder()` -> GET users/me/labels (exact name match, else `FolderNotFound`);
    `list_ids()` -> GET users/me/messages?labelIds&q=after:yyyy/mm/dd, follows `nextPageToken`;
    `fetch_raw()` -> GET users/me/messages/<id>?format=raw, checks `labelIds` contains folder id (`WrongFolder`), base64url-decodes `raw` (padding restored).
  - GET only; one request at a time; >= 100 ms between requests via `time.monotonic()` / `time.sleep()` (module attributes); no retries.
  - The bearer token is read from the callable per request.
  - Errors: httpx error/timeout, 429, 5xx -> `SourceUnavailable`; 401 -> `AuthRevoked`. Messages carry method, path, status only.

## Decisions not covered by docs
- Any other non-200 status (e.g. 403, 404), invalid JSON, or a missing `emailAddress`/`raw` -> `SourceUnavailable` (contract table has no row for these).
- 401 raises `AuthRevoked` directly; the contract says "401 after refresh". Refresh-then-retry is not done here (no retries); the token callable is expected to deliver a fresh token.
- The first request is not delayed; the spacing is measured from the end of the previous request.

## Reviewer check
- `list_ids` is a generator: errors surface on iteration.
- Constructor is keyword-only, as the tests call it.

## Gates
- `tests/test_mailbox_gmail.py`, `test_mailbox_oauth.py`, `test_mailbox_credentials.py`: 22 passed.
- Full `-m "not slow"` suite: see below.
