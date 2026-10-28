# Data Model: Import Candidate Homes from Portal Alert Emails

Phase 1 output for [plan.md](plan.md). Extends the existing local database (`app/db.py`). New tables
are created alongside the existing ones; existing tables get nullable columns only, so current data
keeps working.

## New: `import_runs`

One user action importing a batch (CLI folder or UI selection).

| Field | Type | Rules |
|---|---|---|
| `run_id` | integer, key | increasing |
| `started_at` | ISO timestamp | local time of the import |
| `origin` | text | `cli` or `ui` |
| `n_imported`, `n_already`, `n_rejected`, `n_failed` | integer | sum = number of messages supplied (FR-002) |
| `n_new_listings`, `n_updated_listings` | integer | for the summary |

## New: `alert_emails`

One supplied message, whatever its outcome (FR-010).

| Field | Type | Rules |
|---|---|---|
| `email_id` | text, key | `Message-ID` header if present, else `sha256:<hash of raw bytes>` |
| `content_hash` | text | sha256 of raw bytes |
| `file_name` | text | name as supplied (and mbox index if any) |
| `sender` | text | address of the original sender (inner message if forwarded) |
| `alert_date` | ISO date-time | original alert's `Date` header (inner if forwarded) |
| `forwarded` | 0/1 | |
| `alert_type` | text | `new_listings` · `other_idealista` · `not_idealista` · `unknown` |
| `outcome` | text | `imported` · `rejected` · `failed` (an "already imported" copy is not stored again) |
| `reason` | text | required when outcome ≠ `imported`; names what was expected and not found |
| `reader_version` | text | version of the alert reader that produced the outcome |
| `raw` | bytes | full message as received (kept in full, local only) |
| `first_run_id`, `last_run_id` | integer → `import_runs` | |

State transitions: `failed`/`rejected` → `imported` only by re-processing with a newer
`reader_version` (US3-3). Re-processing never deletes sightings already derived; it re-derives them.

## New: `sightings`

One appearance of one listing in one alert email.

| Field | Type | Rules |
|---|---|---|
| `email_id` | text → `alert_emails` | |
| `listing_id` | text → `listings` | `idealista:<code>` |
| `seen_at` | ISO date-time | = `alert_emails.alert_date` |
| `price`, `area_m2`, `bedrooms` | number, nullable | only values stated in the email; never inferred |
| `property_type` | text, nullable | normalised with the existing type mapping |
| `location_text` | text, nullable | exactly as in the email |
| `link_tracking` | text, nullable | as found (FR-015) |
| `html_text_mismatch` | text, nullable | which fields disagreed between HTML and text parts (FR-017) |
| `raw_block` | text | the part of the email this sighting was read from |

Key: (`email_id`, `listing_id`). Re-importing the same email adds nothing.

## Extended: `listings`

New nullable columns:

| Field | Type | Rules |
|---|---|---|
| `floor`, `elevator`, `terrace`, `garage`, `pool` | nullable | null = "unknown" in the UI (FR-011) |
| `location_text` | text | last location text seen, shown when zone not recognised |
| `field_sources` | JSON map | field → `manual` · `csv` · `alert` · `idealista_api` (R5) |
| `availability` | text | `active` (default) · `gone` (FR-019); independent of `status` |
| `availability_changed_at` | ISO date | |
| `merged_into` | text → `listings`, nullable | set when the user merges this listing into another (FR-018) |
| `first_run_id` | integer → `import_runs`, nullable | run that first detected it (US5) |

Changed rules:
- `zone_id` MAY be null for alert listings whose location text matches no known zone (FR-013).
- `first_seen`/`last_seen` for alert listings are min/max `sightings.seen_at`.
- `price` for alert listings = price of the latest-dated sighting (ties: higher price), unless
  `field_sources.price` is `manual`/`csv` (FR-023).
- Listings with `merged_into` set are not shown as separate rows in the ranking; their links,
  sightings and history are shown on the target.

## Extended: `price_history`

No schema change. Rows from alerts use the sighting date as `day`. Merged listings' history is read
together with the target's.

## New reference data: known zones

`config/zones_madrid_region.csv` (tracked): INE municipality code, municipality name, source, as-of
date; 179 rows for province 28. Madrid districts stay as seeded by `app/etl/indicators.py`.

## Derived at ranking time (not stored)

- **Possible duplicate pairs** (R8): same zone, type, bedrooms; area within 3 %, price within 5 %;
  none of those values null; both active and unmerged.
- **Flags added**: `<field> unknown` for hard filters on null fields; `zone not recognised: "<text>"`;
  `alert says <value> (<date>)`; `conflicting prices on <date>`; `possible duplicate of <id>`;
  `no longer available` (when `availability = gone`).
- **Scoring version**: `SCORING_VERSION = 2`, returned with the ranking and exported.

## Validation rules (from the spec)

| Rule | Source |
|---|---|
| Outcome counts in a run sum to messages supplied | FR-002 |
| A failed/rejected email creates or changes no listing or sighting | FR-009 |
| No sighting field is set unless the email states it | FR-011, SC-005 |
| Alerts never write null over a known value, nor overwrite `manual`/`csv` fields | FR-011, FR-023 |
| `availability` changes only by user action | FR-019 |
| Merge only by user action | FR-018 |
