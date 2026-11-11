# T057 review — [PASS]

Reviewed `git diff jorgevr/Implementation...HEAD` and `app/mailbox/gmail.py` in full. Gates run with CASA_* in a temp folder:
compileall OK; `tests/test_mailbox_gmail.py` 11 passed; anonymise check exit 0; requirements.txt diff empty; no real network.

## Checks
- [OK] Only files touched: `app/mailbox/gmail.py` and `handoffs/T057-dev.md`. No new dependency (httpx already used by oauth).
- [OK] GET only, paths: gmail.py:55 `self._get("users/me/profile")`, :61 `"users/me/labels"`, :69 `"users/me/messages"`, :78 `f"users/me/messages/{message_id}"`. Only `self._client.get` (:36) exists; no other verb.
- [OK] List params gmail.py:67 `{"labelIds": folder_id, "q": f"after:{after.strftime('%Y/%m/%d')}"}`; pagination :72-75 `token = data.get("nextPageToken") ... params = {**params, "pageToken": token}`.
- [OK] fetch_raw: :80 `if folder_id not in (data.get("labelIds") or []): raise WrongFolder` (checked before raw is used); decode :85 `base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4))` handles missing padding.
- [OK] Mapping: :42 `status == 401` -> AuthRevoked; :44 `status != 200` -> SourceUnavailable (429/5xx); :39 `except httpx.HTTPError` (timeouts, transport) -> SourceUnavailable; FolderNotFound only from label-name miss (:64), matching the contract ("label name not found").
- [OK] No retries: single call per `_get`.
- [OK] Clock via module attrs: :10 `import time`, :30 `time.monotonic()`, :32 `time.sleep(wait)`.
- [OK] Spacing also after errors: :37-38 `finally: self._last_request = time.monotonic()` wraps the call, so set on exceptions too (HTTP error statuses return normally, also stamped).
- [OK] Secrets: token only in the header (:33); never in URL/params (:36 params carry no secret). Exception texts are method/path/status/type name only (:40 `type(exc).__name__`, `from None` drops chained exc whose text could include URL). No logging in the module. (Message ids appear in the path text; not secrets.)
- [OK] Handoff accurate, and documents the "other non-200 -> SourceUnavailable" decision (matches :44-45) plus the 401-without-refresh and first-request-undelayed decisions.

## Notes (non-blocking)
1. gmail.py:44 `if status != 200: raise SourceUnavailable(...)` — 403 is NOT mapped to AuthRevoked. The contract table lists only 401 for AuthRevoked, so this is compliant, and the handoff states it. If the task text "401/403" meant 403 → AuthRevoked, that would be a spec change; Gmail 403 is also used for rate limits (`rateLimitExceeded`), so SourceUnavailable is defensible. Reviewer/user should confirm.
2. 404 on `fetch_raw` (message deleted between list and fetch) → SourceUnavailable (:44), stops the whole sync; contract has no row. Documented decision; acceptable for v1 but worth knowing.
3. Test gap: `tests/test_mailbox_gmail.py` has no test for 401 → AuthRevoked, label-not-found → FolderNotFound, or 403/404 (grep finds only 429/5xx/timeout cases at :194-225). Those branches (gmail.py:42-43, :64) are unexercised. Tests are the tests-task's scope, not a dev defect.
4. gmail.py:71 `yield item["id"]` and :61-63 `label.get(...)` raise KeyError/AttributeError on malformed bodies rather than SourceUnavailable; :78 `message_id` is interpolated into the path unquoted. Robustness only; ids come from Gmail.
5. Relies on the injected client having `base_url=BASE_URL` (relative paths); the tests' client does so. `BASE_URL` is exported for the wiring task.
