# T041 dev handoff (app/main.py)

- `PATCH /api/listings/{id}` accepts `price` and `area_m2` (finite number > 0, bool rejected) and `bedrooms`
  (int >= 0, bool/float rejected; 0 is valid). Stored, `field_sources[field] = "manual"`, then
  `derive.derive_listing`. Validation runs before any write, so a mixed invalid body changes nothing.
- Decision not in the docs: `null` for these fields returns 400 (clearing a user value is not specified).
- `scoring_version` in `/api/export.csv` already existed (T029); nothing added.
- price_history is not written on a manual price PATCH (docs silent); added `import math`.
- Gates: compileall ok; pytest -m "not slow": 386 passed, 1 failed (the T038 test above, test bug);
  anonymise check ok; forbidden-path diff clean (only tests/handoffs from the test branches); requirements diff empty.
