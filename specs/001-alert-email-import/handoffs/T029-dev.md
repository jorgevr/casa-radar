# T029 dev handoff

File changed: `app/main.py` only (no db.py/scoring.py change; `merged_into`, `published_at`, `price_updated_at` columns and `SCORING_VERSION = 2` already existed; `price_updated_at` was already derived by T028, so the listings test passed before the code change).

## Changes
- `POST /api/listings/{id}/merge` body `{"into": id}`: 400 bad body or self-merge, 404 unknown source or target, 409 if the merge would close a cycle (walks the target's `merged_into` chain). Sets `merged_into`, returns `{ok, id, merged_into}`.
- `GET /api/listings`: still a list; each listing gains `links` and `sightings` via `with_provenance`. `published_at`/`price_updated_at` come from the listings row (already in `SELECT *`).
- `/api/export.csv`: appends `published_at`, `price_updated_at`, `found_via`, `scoring_version` (user decision in T025-tests.md). `found_via` is always `""` until T034.

## Decisions the docs do not cover
- `links` shape is `{"direct": [...], "tracking": [...]}` (distinct, order of appearance): the listing's own url plus sighting links, including those of listings merged into it (chains resolved; cycle members have no target). Contract only says "direct and tracking, merged listings included".
- `sightings` for a listing also include those of listings merged into it, sorted newest `alert_date` first.
- Re-merging an already merged listing elsewhere is allowed (retargets); only cycles are refused. Merge is not undoable via API (not in task).
- Other fields listed in contracts/api.md (`scoring_version`, `categories`, etc.) are later tasks; not added.

## Reviewer checks
- Sightings come from the `sightings` JOIN `alert_emails`; a manual listing returns empty `sightings`.
- Ad hoc check (not committed): self 400, unknown 404, missing `into` 400, A into B 200, B into A 409.
- Combined price history for merged listings is not changed here (scoring.py handled by T028).
