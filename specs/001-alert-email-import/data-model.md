# Data Model: Import Candidate Homes from Portal Alert Emails

Phase 1 output for [plan.md](plan.md). Extends the local SQLite database (`app/db.py`, untracked
after prerequisite P0). New tables are created alongside the existing ones; existing tables get
nullable columns only (idempotent `ALTER TABLE … ADD COLUMN` on connect), so current data keeps
working. Secrets are never stored here (see [Outside the database](#outside-the-database)).

## New: `import_runs`

One sync (scheduled or "sync now") or one file import.

| Field | Type | Rules |
|---|---|---|
| `run_id` | integer, key | increasing |
| `kind` | text | `sync_scheduled` · `sync_manual` · `file_cli` · `file_ui` · `reprocess` |
| `started_at`, `finished_at` | ISO timestamp | `finished_at` null while running |
| `status` | text | `running` · `ok` · `failed` · `interrupted` |
| `error` | text, nullable | reason when `failed` (never contains secrets) |
| `n_found` | integer | emails found (sync) or supplied (files) |
| `n_imported`, `n_already`, `n_rejected`, `n_failed` | integer | sum = `n_found` when finished (FR-002, SC-004) |
| `n_new_listings`, `n_updated_listings`, `n_price_changes` | integer | for the summary |
| `notes` | JSON list | non-failing notices: unrecognised attributes, "folder identity changed" |

## New: `alert_emails`

One message, whatever its outcome (FR-010). Never deleted.

| Field | Type | Rules |
|---|---|---|
| `email_id` | text, key | `Message-ID` header if present, else `sha256:<hash of raw bytes>` |
| `mailbox_id` | text, unique, nullable | Gmail message id when it came from sync |
| `content_hash` | text | sha256 of raw bytes |
| `origin` | text | `mailbox` · `file` |
| `file_name` | text, nullable | name as supplied (and mbox index) |
| `sender` | text | original sender (inner message if forwarded) |
| `subject` | text | original subject, decoded |
| `search_name` | text, nullable | the part after `en tu búsqueda:` (R9) |
| `alert_date` | ISO date-time | original alert's `Date` header |
| `forwarded` | 0/1 | |
| `alert_type` | text | `new_listing` · `price_drop` · `unsupported` · `not_alert` |
| `outcome` | text | `imported` · `rejected` · `failed` |
| `reason` | text, nullable | required when outcome ≠ `imported`: what was expected and not found |
| `reader_version` | text | e.g. `idealista-2026.10` |
| `category` | text | derived from `subject` by the current rules; `unknown` if none or conflicting (FR-031) |
| `category_rules_matched` | JSON list | rules that matched, for the conflict flag |
| `raw` | blob | full message as received (local only) |
| `first_run_id`, `last_run_id` | integer → `import_runs` | |

Uniqueness: a message whose `email_id` or `mailbox_id` already exists counts as "already processed"
and is not stored again (FR-026, spec edge case "same email in a file and in the mailbox").

State transitions of `outcome`: `failed`/`rejected` → any, only by a user re-process with a reader
version newer than the stored one (US4-3); re-processing re-derives sightings, never deletes the
email.

## New: `sightings`

One appearance of one listing in one alert email.

| Field | Type | Rules |
|---|---|---|
| `email_id` | text → `alert_emails` | |
| `listing_id` | text → `listings` | `idealista:<code>` (same id as the existing API client) |
| `alert_type` | text | `new_listing` · `price_drop` (copied from the email) |
| `seen_at` | ISO date-time | = `alert_emails.alert_date` |
| `price` | number, nullable | card price as stated |
| `previous_price` | number, nullable | price drops only: the stated "ha bajado de" price |
| `area_m2`, `bedrooms`, `floor` | number, nullable | only if stated |
| `exterior`, `elevator`, `garage` | 0/1, nullable | only if stated; absence = null, never 0 (FR-003) |
| `type_text` | text, nullable | as in the title, e.g. `Chalet pareado` |
| `property_type` | text, nullable | mapped type (R9); null for developments |
| `new_build_stated` | 0/1, nullable | 1 when the email states new-build (R9); never 0 from absence |
| `development` | 0/1 | 1 for `Promoción` / `/obra-nueva/` |
| `unit_description` | text, nullable | developments: description as stated |
| `location_text` | text, nullable | as in the title |
| `link_tracking` | text | as found (FR-015) |
| `link_direct` | text | path without query, derived from the email |
| `unrecognised` | JSON list | attribute tokens not in the reader's list |
| `raw_block` | text | the HTML fragment it was read from |

Key: (`email_id`, `listing_id`).

## Extended: `listings`

New nullable columns:

| Field | Type | Rules |
|---|---|---|
| `floor`, `exterior`, `elevator`, `garage`, `terrace`, `pool` | nullable | null = "unknown" in the UI (FR-011) |
| `location_text` | text | from the latest sighting; shown when zone not recognised |
| `development` | 0/1 | FR-034 |
| `unit_description` | text | developments |
| `new_build_origin` | text | `email` · `category` · `user` · null (FR-033) |
| `field_sources` | JSON map | field → `manual` · `csv` · `alert` · `idealista_api` |
| `published_at` | ISO date, nullable | earliest `new_listing` sighting (FR-036) |
| `price_updated_at` | ISO date, nullable | latest sighting that changed the price (FR-036) |
| `categories` | JSON list | distinct sighting categories, for "found via" (FR-032) |
| `availability` | text | `active` (default) · `gone` (FR-019); independent of `status` |
| `availability_changed_at` | ISO date | |
| `merged_into` | text → `listings`, nullable | user merge (FR-018) |
| `first_run_id` | integer → `import_runs` | run that first detected it (US6) |

Derivation (R11), recomputed for a listing whenever one of its sightings changes:

- `price` = price of the latest-dated sighting (ties: higher); not written if
  `field_sources.price ∈ {manual, csv}` (FR-023).
- `area_m2`, `bedrooms`, `floor`, `exterior`, `elevator`, `garage`, `property_type`,
  `location_text` = latest non-null sighting value; same `manual`/`csv` protection; never null over a
  known value (FR-011).
- `new_build` = 1 if any sighting states it (`new_build_origin = email`); else 1 with
  `new_build_origin = category` if a sighting's category is `new-build`; a user value
  (`new_build_origin = user`) is never changed.
- `zone_id` from `location_text` (R10); null when not recognised.
- `first_seen`/`last_seen` = min/max `seen_at`.
- `published_at`, `price_updated_at`, `categories` as in the table above.

## Extended: `price_history`

| Field | Type | Rules |
|---|---|---|
| `listing_id`, `day`, `price` | existing | |
| `origin` | text, nullable | `alert` · `alert_previous` · null for existing rows |
| `email_id` | text, nullable | sighting that produced it |

For alert listings the rows with `origin` `alert`/`alert_previous` are rebuilt from sightings on
each derivation: one `alert` row per date where the price differs from the previous one, and one
`alert_previous` row per price drop, dated the same day and ordered before it. The ranking reads
history ordered by `day`, then `alert_previous` first, then `rowid`.

## New: `mailbox_state` (single row)

| Field | Type | Rules |
|---|---|---|
| `provider` | text | `gmail` |
| `account` | text | address from `users.getProfile`, shown in the UI; never a secret |
| `label_name`, `label_id` | text | configured folder; id re-resolved each sync (R5) |
| `auth_state` | text | `not_configured` · `valid` · `revoked` (covers expired) |
| `auto_sync` | text | `on` · `paused_auth` (FR-029) |
| `backfill_from` | ISO date | set at first sync: today − 30 days (FR-027) |
| `last_attempt_at`, `last_attempt_status` | | |
| `last_success_at` | ISO timestamp | |
| `last_error_at`, `last_error` | | reason only, never secrets |
| `running_run_id` | integer, nullable | lock indicator for the UI; the real lock is in-process |
| `progress_done`, `progress_total` | integer | during a sync (SC-010) |

State transitions of `auth_state`:

```text
not_configured --setup ok--> valid
valid --invalid_grant / 401 after refresh--> revoked   (auto_sync := paused_auth)
revoked --re-authorise ok--> valid                     (auto_sync := on)
valid|revoked --user "disconnect"--> not_configured    (token file deleted)
```

## Configuration files (tracked unless noted)

| File | Content |
|---|---|
| `config/alert_categories.yaml` | category rules (R12); no personal data |
| `config/zones_madrid_region.csv` | INE municipalities, province 28, with source and date (R10) |
| `config/zone_aliases.yaml` | user-added location text → zone id (R10); untracked, `.example` tracked |
| `config/needs.yaml` | **untracked after P0**; `config/needs.example.yaml` tracked |

## Outside the database

`%LOCALAPPDATA%\casa-radar\` (override `CASA_APPDATA`): `client_secret.json` (copied by the user),
`token.bin` (DPAPI-encrypted refresh token). Never inside the repository, never logged, never
returned by any API (FR-030).

## Derived at ranking time (not stored)

- Possible duplicate pairs (R15).
- Flags: `<field> unknown` on hard filters; `zone not recognised: "<text>"`;
  `alert says <value> (<date>)`; `alert says previous price <X>, recorded <Y>`;
  `conflicting prices on <date>`; `possible duplicate of <id>`; `no longer available`;
  `development: no unit chosen`; `new-build from alert category, confirm`;
  `found via: unknown search`; `category rules conflict: <rules>`; `type not recognised: <text>`.
- `SCORING_VERSION = 2`.

## Validation rules

| Rule | Source |
|---|---|
| Run counts sum to emails found | FR-002, SC-004 |
| Failed/rejected email creates or changes no listing or sighting | FR-009 |
| No sighting field set unless stated; absence never means "no" | FR-003, FR-011, SC-005 |
| Alerts never overwrite `manual`/`csv` fields nor write null over known values | FR-011, FR-023 |
| Price drop never creates a second listing for a known code | FR-035 |
| Derived values independent of processing order | FR-008, Article VIII |
| Every stored mailbox message carries the configured label id | FR-016 |
| `availability` and merges change only by user action | FR-018, FR-019 |
