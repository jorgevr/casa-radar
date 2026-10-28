# Contract: Local HTTP API (used by the UI)

Served only on `127.0.0.1` by the existing local server.

## `POST /api/alerts/import`

Request:

```json
{ "files": [ { "name": "alerta.eml", "content_base64": "..." } ] }
```

Response `200`:

```json
{
  "run_id": 7,
  "emails": { "total": 30, "imported": 26, "already": 1, "rejected": 2, "failed": 1 },
  "listings": { "new": 12, "updated": 3, "price_changes": 2, "unchanged": 26 },
  "problems": [ { "file": "alerta-2026-10-20.eml", "outcome": "failed",
                  "reason": "html bloque 3: se esperaba código de anuncio", "evidence": "…" } ],
  "scoring_version": 2
}
```

`400` only for a malformed request (not for unreadable emails, which are reported in `problems`).

## `GET /api/alerts/emails?outcome=failed|rejected|imported`

List of stored emails with `email_id`, `file_name`, `alert_date`, `outcome`, `reason`,
`reader_version`. Raw content is not returned in the list.

## `GET /api/alerts/emails/{email_id}/raw`

The stored message as received (for inspection; local only).

## `POST /api/alerts/reprocess`

Body `{ "scope": "failed" | "all" }`. Response as for import.

## Changes to existing endpoints

- `GET /api/listings`: each listing gains `floor`, `elevator`, `terrace`, `garage`, `pool`,
  `location_text`, `availability`, `first_run_id`, `sightings` (count and latest date),
  `links` (direct and tracking, including merged listings), `field_sources`; response includes
  `scoring_version`. New query parameter `new_since_last_import=true` (US5).
- `PATCH /api/listings/{id}`: accepts `availability: "active" | "gone"` (FR-019).
- `POST /api/listings/{id}/merge` body `{ "into": "<listing id>" }`: user merge (FR-018).
- `GET /api/export.csv`: adds a `scoring_version` column.
