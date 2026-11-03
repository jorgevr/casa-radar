# T026 fix 4 - tests (loop 5)

New file: `tests/test_derive_new_build_api.py` (no existing test edited; expected values by hand in comments).

- `test_alert_new_build_overrides_api_zero`: API listing (new_build 0, field_sources idealista_api) + alert stating new-build => new_build 1, origin 'email', label 'alert', alert_flags == [].
- `test_alert_first_then_api_refresh_then_derive_again`: alert derived, API refresh writes 0 (label back to idealista_api), derive again => 1, 'email', 'alert', no flags.
- `test_alert_not_stating_new_build_leaves_api_zero`: stays 0, origin None, label idealista_api, no flag.
- `test_user_zero_still_protected_and_flagged[csv|manual]`: stays 0, flag `la alerta dice sí (27/10/2026)`.
- `test_origin_user_still_protected`: origin 'user' kept, same flag.

## Evidence against 3944bad (detached temp worktree, since removed)
2 failed, 4 passed:
- test_alert_new_build_overrides_api_zero: `assert 0 == 1` (idealista_api value protected)
- test_alert_first_then_api_refresh_then_derive_again: `assert 0 == 1` (same cause; fails at the first derive, so the refresh half is only exercised on the fixed code)

## Current worktree
New file 6 passed; full `pytest -m "not slow"` 160 passed; compileall clean.
