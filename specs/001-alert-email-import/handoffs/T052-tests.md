# T052 tests handoff — Gmail MailSource client (iteration 1, review fixes)

## Files (this task)
- `tests/test_mailbox_gmail.py`
- `specs/001-alert-email-import/handoffs/T052-tests.md`

## What each test asserts

1. **`test_every_request_is_allowed_get`** (FR-016, mail-source contract): exercises `account()`, `resolve_folder("Alerts")`, `list_ids(folder_id, 2026-10-01)`, `fetch_raw(folder_id, "m1")` against `httpx.MockTransport`. Asserts every recorded request is `GET` and its path is exactly one of `/gmail/v1/users/me/profile`, `/gmail/v1/users/me/labels`, `/gmail/v1/users/me/messages`, or `/gmail/v1/users/me/messages/<id>` (message-item path allows no further segments). Asserts profile, labels, messages-list and message-item endpoints were each requested at least once; asserts return values `account()=="user@example.com"`, `resolve_folder("Alerts")=="LBL1"`, `ids==["m1"]`; and asserts every message fetch carries `format=raw`.

2. **`test_list_ids_carries_label_and_after_and_follows_pagination`**: `list_ids("LBL9", 2026-09-15)` issues list calls whose query contains `labelIds=LBL9` and `q=after:2026/09/15`. First response returns `nextPageToken`; asserts pagination is followed (exactly two list requests, second carries `pageToken=page-2`) and collected ids are `["m1","m2"]`.

3. **`test_fetch_raw_base64url_decodes`**: `fetch_raw` base64url-decodes the `raw` field using a **hand-computed literal** encoded string `"-_8"` (not derived from code). Calculation (in test comment): raw bytes `0xFB,0xFF` (2 bytes, not a multiple of 3 → stripped padding) → bits `11111011 11111111` → 6-bit groups `111110`(62=`-`), `111111`(63=`_`), `111100`(60=`8`, 2 padding bits) → padded urlsafe base64 `"-_8="`, Gmail/stripped form `"-_8"` (contains `-` and `_`, no `=`). Expected decoded bytes `b"\xfb\xff"`.

4. **`test_fetch_raw_message_lacking_label_raises_wrong_folder`**: fetched message JSON whose `labelIds` do not include the requested folder id causes `fetch_raw` to raise `app.mailbox.WrongFolder`.

5. **`test_429_5xx_timeout_raise_source_unavailable`** (parametrized 429, 500, 503, `httpx.TimeoutException`): `list_ids` raises `app.mailbox.SourceUnavailable` and the handler records **exactly 1 call** (no retries).

6. **`test_fetch_raw_5xx_timeout_raise_source_unavailable`** (parametrized 500, `httpx.TimeoutException`): `fetch_raw` raises `app.mailbox.SourceUnavailable` and the handler records **exactly 1 call** (no retries).

7. **`test_requests_spaced_at_least_100ms`**: patches `time.monotonic`, `time.perf_counter`, `time.time` and `time.sleep` together to a shared fake clock (`sleep` advances the clock). Performs `list_ids` (2 pages via `nextPageToken`) plus `fetch_raw`, recording **>= 3 requests**, and asserts every consecutive gap `later - earlier >= 0.1s`.

## Construction decision (coordinator-directed; NEW, not in tasks.md/contracts)

- **`GmailSource` constructor (pending approval before T057)**: tests use a single keyword-only shape `GmailSource(client=<httpx.Client with MockTransport, base_url=https://gmail.googleapis.com/gmail/v1/>, access_token=<zero-arg callable returning FAKE_TOKEN>)` with no try/except probing/fallbacks. This is proposed for testability and is not specified in `tasks.md` or `contracts/mail-source.md`; it must be approved by the user/coordinator before T057 is dispatched.
- Errors imported as `from app.mailbox import WrongFolder, SourceUnavailable` per mail-source contract.
- Spacing test requires the implementation to read/advance time via module attributes (`time.monotonic`/`time.perf_counter`/`time.time`/`time.sleep`), not via `from time import ...` bindings.

## Failure reason observed (accepted, right reason)

Command (worktree root, isolated env `CASA_DB/NEEDS/APPDATA` under `%TEMP%\casa-agent-T052`):
`python -m pytest tests/test_mailbox_gmail.py -q`

Result: **11 failed**. Every test failed individually at import inside the test with `ModuleNotFoundError: No module named 'app.mailbox'` (raised from `from app.mailbox.gmail import GmailSource` or `from app.mailbox import WrongFolder/SourceUnavailable`). No collection error, no syntax/fixture errors. This is the accepted pre-implementation failure for T052.

## Gates (iteration 1)

- `python -m compileall -q app tests` — pass
- `python tests/fixtures/anonymise_eml.py --check tests/fixtures/emails` — pass
- `git diff --name-only main...HEAD` — only `tests/test_mailbox_gmail.py` and `specs/001-alert-email-import/handoffs/T052-tests.md`
- `git diff main...HEAD -- requirements.txt` — empty

## Reviewer notes

- Fully offline (`no_network` fixture + `httpx.MockTransport` only); no Google/browser/DPAP I, no real secrets (only `fake-access-token-for-tests`).
- Did not edit `app/`, `tests/conftest.py`, `requirements.txt`, `config/`, `data/`, `tasks.md`, or `T052-review.md`. No assertion weakened.
