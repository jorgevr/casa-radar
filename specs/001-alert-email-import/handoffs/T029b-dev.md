# T029b dev handoff

Added `GET /api/listings/{lid:path}/price-history` in `app/main.py` (only code file touched).

- Returns `[{day, price, origin}]` (no email_id) from `price_history` for exactly that listing id; merged listings answer with their own rows only.
- 404 `listing not found` for an unknown id; `[]` when no rows. Read-only, parameterised SQL.
- Ordering `ORDER BY day, (origin = 'alert_previous') DESC, rowid` is duplicated from `scoring.py` (line ~296; no shared helper exists, scoring.py not edited).
- Route declared before `GET /api/listings`, same `{lid:path}` style as the merge endpoint.

Reviewer: confirm that a 404 body text is not constrained by docs.
