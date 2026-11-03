# T041 dev handoff (app/main.py)

- `PATCH /api/listings/{id}` accepts `price` and `area_m2` (finite number > 0, bool rejected) and `bedrooms`
  (int >= 0, bool/float rejected; 0 is valid). Stored, `field_sources[field] = "manual"`, then
  `derive.derive_listing`. Validation runs before any write, so a mixed invalid body changes nothing.
- Decision not in the docs: `null` for these fields returns 400 (clearing a user value is not specified).
- `scoring_version` in `/api/export.csv` already existed (T029); nothing added.
- price_history is not written on a manual price PATCH (docs silent); added `import math`.
- Gates: compileall ok; pytest -m "not slow": 386 passed, 1 failed (the T038 test above, test bug);
  anonymise check ok; forbidden-path diff clean (only tests/handoffs from the test branches); requirements diff empty.

## Review 1 fix (finding 1)
- All unit values are range-checked before any write: price and area_m2 must be finite, > 0 and strictly
  below `UNIT_MAX` = 1e12; bedrooms an int in 0..2**63-1 (`SQLITE_INT_MAX`). Out-of-range gives 400.
- Every write of the PATCH (status, notes, units, availability, new_build, derivations) now runs in one
  try block ending in `commit()`; any exception (including unexpected ones) does `conn.rollback()` and re-raises,
  so a failed request leaves nothing pending on the shared connection.
- Findings 2 and 3 untouched (spec decisions pending). Bounds follow handoffs/T041-tests.md addendum.
