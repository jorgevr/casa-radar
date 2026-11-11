STATUS: [PASS]

Re-review (iteration 2) of `tests/test_mailbox_gmail.py` at commit 66af9c4 (supersedes the iteration-1 FAIL). Reviewed independently from the file, the T052/T057 text, `contracts/mail-source.md` and research R7. One material defect remains (item A); everything else is resolved or minor.

## Run
Offline, with `CASA_DB/NEEDS/APPDATA` under `%TEMP%\casa-review-T052`: **11 failed**, all `ModuleNotFoundError: No module named 'app.mailbox'` raised at `tests/test_mailbox_gmail.py:53` or at the in-test imports (L172, L199, L224). There are no syntax, fixture or other import errors. Accepted failure reason confirmed.

## Scope
`git diff main...HEAD --stat` touches only `tests/test_mailbox_gmail.py` and `handoffs/T052-tests.md`. Nothing under `app/`, `conftest.py`, `requirements.txt`, `config/` or `data/`. The only secret-like string is `fake-access-token-for-tests` (L25). Tests use `no_network` and `httpx.MockTransport`.

## A. MATERIAL: a correct implementation fails test 1 (L81)
- `test_every_request_is_allowed_get` serves `"raw": "raw-bytes"` (L81).
- `"raw-bytes"` is not valid base64url: 9 data characters is 1 more than a multiple of 4.
- I ran `base64.urlsafe_b64decode('raw-bytes')`, with and without extra padding. It raises `binascii.Error: ... number of data characters (9) cannot be 1 more than a multiple of 4`.
- A correct `fetch_raw` that base64url-decodes will raise at L89 (`raw = source.fetch_raw(folder_id, "m1")`). The test fails a correct client, or forces the client to swallow decode errors.
- `assert raw is not None` (L101) is also weak. Once the payload is valid, assert the exact decoded bytes.
- Required change: use a valid payload (the file already uses `"cmF3"` elsewhere, L179 and L274), and assert `raw == b"raw"` at L101.

## Previous required changes
1. **Base64 payload:** RESOLVED. L149-150 `encoded_raw = "-_8"`, `expected = bytes([0xFB, 0xFF])`. I verified independently:
   - 0xFB 0xFF = 11111011 11111111, which splits into 111110 111111 1111(00) = 62, 63, 60 = `-`, `_`, `8`.
   - `base64.urlsafe_b64encode(bytes([0xFB,0xFF]))` gives `b'-_8='`, so the stripped-padding form is `-_8`, with `-` and `_` present.
   - Standard `b64decode` would reject or mis-decode `-` and `_`, so the test really discriminates. The literal is correct.
   - The comment at L143-148 gives the calculation. The dead code is gone.
2. **Constructor probe:** RESOLVED in form. `_make_source` (L51-62) now uses a single signature, `GmailSource(client=client, access_token=lambda: FAKE_TOKEN)`, with no try/except. It is flagged in the comment at L60-61 as not in the docs (see Open decisions).
3. **Spacing test:** PARTLY RESOLVED (L240-288).
   - Now ≥3 requests (two list pages plus one fetch, L280-283), with 2 gaps checked at L285-288 `assert later - earlier >= 0.1`.
   - It patches `monotonic`, `perf_counter`, `time` and `sleep` (L255-258).
   - I checked float arithmetic: cumulative gaps of the shape 1000.0 → 1000.1 → 1000.2 are `0.10000000000002274` each, all ≥0.1. No false failure from float rounding for a client that sleeps 0.1.
   - A correct client using `from time import sleep`, `threading.Event.wait`, or an async sleep would still fail; that is an open decision, not a defect.
4. **`test_every_request_is_allowed_get` strength:** RESOLVED except A.
   - `_is_message_item_path` (L32-34) is `re.fullmatch(r"/gmail/v1/users/me/messages/[^/]+", path)`, so no sub-segments.
   - Each endpoint's presence is asserted (L93-96).
   - `assert account == "user@example.com"` (L98), `assert folder_id == "LBL1"` (L99), `assert ids == ["m1"]` (L100).
   - `format=raw` is asserted: `qs.get("format") == ["raw"]` (L107).
5. **No retries:** RESOLVED. L212 and L237: `assert calls["count"] == 1`.
6. **`fetch_raw` error mapping:** RESOLVED. `test_fetch_raw_5xx_timeout_raise_source_unavailable` (L215-237) covers 500 and timeout. 429 on `fetch_raw` is not covered, which is minor.
7. **Handoff claims:** not trusted; I judged the file only.

## Task behaviour → test
| Behaviour (T052) | Test | Status |
|---|---|---|
| GET only, to the four endpoints | L65-107 (`_assert_only_allowed_gets` L44-48) | Covered; blocked by A |
| `labelIds=<id>` | L136 | Covered |
| `q=after:yyyy/mm/dd` | L137 `== ["after:2026/09/15"]` | Covered |
| Pagination | L131, L133, L138 | Covered |
| base64url decode | L141-167 | Covered, strong |
| Wrong label → `WrongFolder` | L184 | Covered |
| 429/5xx/timeout → `SourceUnavailable` | L188-212, L215-237 | Covered |
| ≥100 ms spacing, clock patched | L240-288 | Covered; implementation-coupled |

## New or remaining observations (minor)
- No over-broad `pytest.raises(Exception)`, no skip/xfail, no `assert True`.
- L283 `assert len(recorded) >= 3` is a guard rather than a behaviour check; fine.
- The spacing test records time at handler call. A client that sleeps after each request instead of before the next also passes.

## Open decisions for the user (interfaces pinned but not in the docs)
1. **Constructor:** `GmailSource(client=<httpx.Client>, access_token=<zero-arg callable returning str>)`, keyword-only (L62). T057 says only "over `httpx.Client(timeout=30)` with base …". Client injection and the token-provider shape are not documented. Decide this before T057.
2. **Base URL / paths:** the injected client's `base_url` is `https://gmail.googleapis.com/gmail/v1/` (L57), and the allowed paths are `/gmail/v1/users/me/...` (L19-22, L32-34).
3. **Clock:** the client must use `time.monotonic`/`perf_counter`/`time.time` and `time.sleep` through the module (L253-258), not `from time import ...` or non-`time` waits.
4. **Token passing:** the tests never assert how the token is sent (for example an `Authorization` header). This is probably fine, but the user should decide whether to pin it.

## Required change for the Test Author
- Fix L81 (and L101) as described in A. No other change is required.

---
## Iteration 2 result (supersedes item A and "Required change" above)
- `git diff ccbfa71 HEAD -- tests/test_mailbox_gmail.py` changes exactly two things plus a comment, all in `test_every_request_is_allowed_get`:
  - L84: `"raw": "cmF3"` (was `"raw-bytes"`, invalid base64).
  - L104: `assert raw == b"raw"` (was `assert raw is not None`).
  - L79-82: a hand-computed comment. I verified independently: `base64.urlsafe_b64decode('cmF3')` is `b'raw'`.
- Blocking issue A: RESOLVED. Nothing else in the test file changed, and no new problem was introduced.
- Run offline (`CASA_*` under `%TEMP%\casa-review-T052`): 11 failed, and all 11 have the same error line `E  ModuleNotFoundError: No module named 'app.mailbox'`. This is the accepted failure for this phase.
- Scope: `git diff main...HEAD --stat` touches only `tests/test_mailbox_gmail.py` and `handoffs/T052-tests.md`.
- The open decisions for the user stay as listed above: the `GmailSource(client=, access_token=)` signature, the base URL and `/gmail/v1/...` paths, clock use through the `time` module attributes, and token passing.
