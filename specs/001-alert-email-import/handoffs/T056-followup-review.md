# T056 follow-up review (re-review of 5ee4a78)

**Verdict: [PASS]** (previous F1 fixed; no new blocking findings)

Reviewed `git diff 56b1b6d HEAD` and the full `git diff jorgevr/Implementation...HEAD`. CASA_* pointed at `%TEMP%\casa-agent`; loopback only, no browser, no Google.

## F1 (drip-feeding client): resolved

- `app/mailbox/oauth.py:162-177` `Handler.handle` arms `timer = threading.Timer(max(deadline - time.monotonic(), 0.0), abort)` per request, `timer.daemon = True`, and `finally: timer.cancel()` around `super().handle()`. No timer outlives its request (cancelled on every path, daemon as a backstop).
- `abort()` calls `self.request.shutdown(socket.SHUT_RDWR)` inside `try ... except OSError: pass`, so an already-closed or reset socket cannot raise from the timer thread.
- `deadline` is now computed once at the top of `_wait_for_redirect` (`:141`), shared by the loop and every handler, so it is absolute. The per-recv `Handler.timeout = remaining` and `server.timeout` are kept, which still covers idle clients and `accept`.
- My earlier reproduction (one byte every 0.4 s, 1.0 s timeout) now returns after **1.2 s** (was 32.1 s). An idle client is still bounded.
- A genuine callback in time is unaffected: the handler writes its response and returns, the timer is cancelled; the existing accept test (wrong-state requests followed by the genuine one, final status 200 and a token exchange) still passes. Only a request still open at the deadline is cut off, which is the intended behaviour.

## Regressions / other checks

- [OK] F2 unchanged: `:143` compare_digest on UTF-8 bytes, 400 for code/error with wrong or missing state, `result.update` only in the genuine branch; the wrong-state code is never stored, used or logged; `log_message` still silent. Timer code logs nothing.
- [OK] Binding `127.0.0.1` and `server.server_close()` in `finally` (`authorize`) unchanged. No new dependency (`socket`, `threading` are stdlib); `requirements.txt` diff empty. Only `app/mailbox/oauth.py`, `tests/test_mailbox_oauth.py`, `handoffs/T056-followup.md` touched.
- [OK] Tests: `--numstat 56b1b6d HEAD` shows tests 43 added / 0 deleted; full follow-up 171 added / 0 deleted, so no existing test line deleted or weakened. New test `test_drip_feeding_local_client_does_not_defeat_the_authorisation_timeout` (1.0 s timeout, one byte per 0.2 s, asserts TimeoutError and < 4 s, sockets closed in `finally`) uses 127.0.0.1 and fake data only, no long sleeps.
- [OK] Fails before / passes after: against 56b1b6d's `oauth.py` (scratchpad copy, repo untouched) the drip test fails and the other 10 pass; on HEAD all 11 pass.
- [OK] Not flaky: ran `tests/test_mailbox_oauth.py` 3 times on HEAD, 11 passed each (3.7 s, 3.6 s, 6.0 s). `python -m compileall -q app tests` passes.

## Notes (non-blocking)

- The timer can in theory fire while a genuine response is being written exactly at the deadline; that request is then cut, which is acceptable at the timeout boundary.
- Module docstring still says "per-connection socket timeout bounded by the time left"; accurate enough, now supplemented by the timer sentence.
