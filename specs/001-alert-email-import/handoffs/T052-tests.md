# T052 tests handoff — Gmail MailSource client

## File added
- `tests/test_mailbox_gmail.py`

## What each test asserts

1. **`test_every_request_is_allowed_get`** (FR-016, mail-source contract): exercises `account()`, `resolve_folder()`, `list_ids()`, `fetch_raw()` against a `httpx.MockTransport` that records every request and returns minimal valid JSON. Asserts every recorded request is `GET` and its path is one of `/gmail/v1/users/me/profile`, `/gmail/v1/users/me/labels`, `/gmail/v1/users/me/messages`, or `/gmail/v1/users/me/messages/<id>` (no other method, no other endpoint).

2. **`test_list_ids_carries_label_and_after_and_follows_pagination`**: `list_ids("LBL9", 2026-09-15)` must issue list calls whose query contains `labelIds=LBL9` and `q=after:2026/09/15` (yyyy/mm/dd). First response includes `nextPageToken`; asserts pagination is followed (two list requests, second carries `pageToken=page-2`) and collected ids are `["m1", "m2"]` in order.

3. **`test_fetch_raw_base64url_decodes`**: `fetch_raw` must base64url-decode the message `raw` field and return the original RFC822-like bytes (tested with UTF-8 bytes including a euro sign to ensure URL-safe decoding, not standard base64).

4. **`test_fetch_raw_message_lacking_label_raises_wrong_folder`**: when the fetched message JSON has `labelIds` that do not include the requested folder id, `fetch_raw(folder_id, message_id)` raises `app.mailbox.WrongFolder`.

5. **`test_429_5xx_timeout_raise_source_unavailable`** (parametrized over 429, 500, 503 responses and `httpx.TimeoutException`): a list request that hits rate-limit/server/unavailable/timeout must raise `app.mailbox.SourceUnavailable` (no retries asserted implicitly by single-shot handler behavior; retry policy is an implementation concern).

6. **`test_requests_spaced_at_least_100ms`**: patches `time.monotonic` and `time.sleep` to a controllable clock, performs two operations (`list_ids` then `fetch_raw`) generating >=2 recorded requests, and asserts each consecutive request timestamp is >= 0.1s after the previous (spacing enforced by the client).

## Construction assumptions / decisions (docs do not fully specify signature)

- `app.mailbox.gmail.GmailSource` is instantiated with an `httpx.Client` (using `MockTransport`, `base_url=https://gmail.googleapis.com/gmail/v1/`). The helper tries `GmailSource(client=..., access_token=lambda: FAKE_TOKEN)`, then positional fallbacks, so the test remains tolerant of the exact constructor once implemented while still importing the real module.
- Errors imported as `from app.mailbox import WrongFolder, SourceUnavailable` per mail-source contract.
- `account()`/`resolve_folder()` are exercised in the "allowed GETs" test because the contract names profile/labels; if the final API differs, the review should align test calls with the implemented contract methods (failure mode today is only the missing module).

## Failure reason observed (right reason)

Command (worktree root, isolated env `CASA_DB/NEEDS/APPDATA` under `%TEMP%\casa-agent-T052`):
`python -m pytest tests/test_mailbox_gmail.py -q`

Result: **9 failed in 48.46s**. Every test failed individually at import inside the test with:
`ModuleNotFoundError: No module named 'app.mailbox'` (raised from `from app.mailbox.gmail import GmailSource` or `from app.mailbox import WrongFolder/SourceUnavailable`). No collection error, no syntax/fixture errors.

## Gates

- `python -m compileall -q app tests` — exit 0
- `python tests/fixtures/anonymise_eml.py --check tests/fixtures/emails` — exit 0
- `git diff --name-only main...HEAD` — (pre-commit) empty; commit will contain only this handoff and `tests/test_mailbox_gmail.py`
- `git diff main...HEAD -- requirements.txt` — empty

## Reviewer notes

- Tests are fully offline (`no_network` fixture + `httpx.MockTransport` only); no Google calls, no secrets/tokens beyond the obviously fake string `fake-access-token-for-tests`.
- Did not edit `app/`, `tests/conftest.py`, `requirements.txt`, `config/`, `data/`, or `tasks.md`.
- The >=100ms spacing test observes real recorded request times; if the implementation spaces requests differently (e.g. before first) the bound check between consecutive calls still applies.
