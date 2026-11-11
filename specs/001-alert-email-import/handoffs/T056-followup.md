# T056 follow-up (review findings F1, F2)

## Changed
- `app/mailbox/oauth.py` `_wait_for_redirect(server, timeout, state)` (new `state` parameter, only caller is `authorize`):
  - F2: a request carrying `code` or `error` whose `state` does not match (constant-time `secrets.compare_digest`, compared as UTF-8 bytes so a non-ASCII state cannot raise TypeError) gets a 400 "Bad request", is ignored, and the wait continues until the deadline. The first callback with the correct state is accepted. The later `compare_digest` check in `authorize` stays.
  - F1: `Handler.timeout = remaining` is set every loop iteration, so each accepted connection gets a socket timeout bounded by the time left; an idle client cannot hold the wait past the deadline.
- `tests/test_mailbox_oauth.py`: three new tests (existing ones untouched).

## Tests (real sockets on 127.0.0.1 only; they do not use `no_network`, which blocks `connect`; no browser, no Google, fake credentials functions monkeypatched, token endpoint is `httpx.MockTransport`)
- `test_idle_local_connection_does_not_defeat_the_authorisation_timeout` (timeout 0.5 s, idle connection, expects TimeoutError, no hang)
- `test_wrong_or_missing_state_callbacks_are_ignored_and_the_genuine_one_is_accepted` (wrong state, missing state, non-ASCII state, error with wrong state: all >= 400; then the genuine callback succeeds, only its code is exchanged, one refresh token saved)
- `test_only_bad_state_callbacks_end_in_timeout_not_in_an_early_failure`
Tests-first confirmed: all three failed before the change on behaviour (hang / PermissionError instead of TimeoutError / wrong-state accepted), not on import errors.

## Decisions not covered by docs
- A callback with `error=` and a wrong/missing state is also ignored (same rule as `code`). Consequence: a genuine Google error redirect always carries our state, so it is still reported.
- F3 and F4 from the review were not requested and are not changed.
- No doc change proposed.

## Gates
compileall OK; `pytest -q -m "not slow"`: 535 passed, 1 skipped, 2 deselected (CASA_* in %TEMP%sa-agent-FU-T056); anonymise check ran without failure; diff vs main lists no forbidden paths (only files merged from Implementation); requirements.txt diff empty.
