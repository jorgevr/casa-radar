# Contract: Local HTTP API (used by the UI)

Served only on `127.0.0.1` by the existing local server. No endpoint returns a secret.

## Mailbox

### `GET /api/mailbox`

```json
{
  "provider": "gmail", "account": "usuario@gmail.com",
  "label_name": "Idealista", "auth_state": "valid", "auto_sync": "on",
  "interval_minutes": 15, "backfill_from": "2026-09-28",
  "last_success_at": "2026-10-28T11:45:02", "last_attempt_status": "ok",
  "last_error": null, "last_error_at": null,
  "out_of_date": false, "running": false, "progress": null,
  "reauthorise_steps": null,
  "app_folder": "C:\\Users\\…\\AppData\\Local\\casa-radar"
}
```

`out_of_date` is true when the last attempt failed or the last success is older than 30 minutes
(FR-028). When `auth_state = revoked`, `reauthorise_steps` lists the exact steps (FR-029).

### `POST /api/mailbox/authorise`

Starts the authorisation flow (opens the browser on this machine). Response `202
{"waiting": true}`; the UI polls `GET /api/mailbox` until `auth_state` changes or 5 minutes pass.

### `PUT /api/mailbox/folder`  `{ "label_name": "Idealista" }`

Resolves and stores the label. `404 {"error": "folder Idealista not found"}` if absent.

### `POST /api/mailbox/sync`

Runs "sync now". `202 {"run_id": 12}`; `409 {"error": "sync already running"}`.

### `POST /api/mailbox/disconnect`

Deletes the stored token; `auth_state = not_configured`.

## Runs and emails

### `GET /api/runs?limit=20` · `GET /api/runs/{run_id}`

Run summary as in [data-model `import_runs`](../data-model.md#new-import_runs), plus `problems`:
`[{email_id, alert_date, subject, outcome, reason}]` and `notices`.

### `POST /api/alerts/import`  `{ "files": [ { "name": "a.eml", "content_base64": "…" } ] }`

File import; response = run summary. `400` only for a malformed request.

### `GET /api/alerts/emails?outcome=failed|rejected|imported` · `GET /api/alerts/emails/{id}/raw`

Stored emails (list without raw); raw message for inspection (local only).

### `POST /api/alerts/reprocess`  `{ "scope": "failed" | "all" }`

Response = run summary.

## Categories

### `GET /api/categories` · `PUT /api/categories`

```json
{ "rules": [ { "contains": "obra nueva en tu zona personalizada", "category": "new-build" } ],
  "search_names": [ { "name": "Viviendas en tu zona personalizada", "category": "unknown",
                      "emails": 5 } ] }
```

`PUT` saves the rules and re-derives categories for all stored emails (FR-031).

## Changes to existing endpoints

- `GET /api/listings`: response gains `scoring_version` and, per listing: `published_at`,
  `price_updated_at`, `categories`, `development`, `unit_description`, `new_build_origin`,
  `floor`, `exterior`, `elevator`, `garage`, `terrace`, `pool`, `location_text`, `availability`,
  `field_sources`, `first_run_id`, `sightings` (count, latest date), `links` (direct and tracking,
  merged listings included). Query `new_since_last_run=true` (US6).
- `PATCH /api/listings/{id}`: also accepts `availability: "active" | "gone"` (FR-019),
  `new_build: true | false | null` (user value, FR-033), and unit values `price`, `area_m2`,
  `bedrooms` (recorded as `manual`, FR-023/FR-034).
- `POST /api/listings/{id}/merge`  `{ "into": "<listing id>" }` (FR-018).
- `GET /api/export.csv`: adds `published_at`, `price_updated_at`, `found_via`, `scoring_version`.
