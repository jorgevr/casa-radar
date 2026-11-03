# T026 fix 3 - tests (round-3 finding: new_build protection)

File: tests/test_derive_new_build_protection.py (new; no app/ or existing test touched).

Asserts (expected values by hand, in comments):
- csv/manual listing with new_build=0 + sighting new_build_stated=1: new_build stays 0, new_build_origin stays
  NULL, field_sources.new_build stays csv/manual, alert_flags == ["la alerta dice sí (27/10/2026)"]. (2 FAIL now: alert overwrites to 1)
- csv/manual new_build=1 + sighting without new_build: stays 1, no flag. (pass)
- csv/manual new_build=1 + sighting stating it: no flag, label kept. (pass)
- Guard: alert-created listing -> new_build 1, origin 'email'. (pass)
- Guard: new_build_origin 'user' never changed. (pass)

Decision: flag value is `sí` (boolean convention); dev must add new_build to the boolean list in `_show`
and route new_build through `protected()` (origin csv/manual). Note the dev must not rely on
new_build_origin, which is NULL for user-entered rows.
Review: the new_build_origin 'user' guard sets the origin by direct UPDATE (no API sets it yet).
Full suite after adding: only the 2 intended failures.
