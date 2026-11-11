# T058 dev handoff — app/alerts_sync.py

## Status: 9 of 11 tests pass; 2 tests look wrong (stopped per AGENTS.md)

## Files
- `app/alerts_sync.py` (new). No other file touched.

## What it does
`sync(conn, source, kind)`, `read_state`/`write_state` (SyncState helpers), `out_of_date(state, now)`,
module-level `threading.Lock` (non-blocking), rules loaded once per run (ValueError -> no rules, run error
`ValueError: <msg>`, status ok), window = first sync today-30d else last success date - 2d, known mailbox_ids
skipped without fetching, source order kept, one transaction per message via `alerts.process_message`,
progress in mailbox_state, label re-resolution (`notice: "folder identity changed"` in the summary when the
id changed), error mapping per R6 (AuthRevoked -> revoked/paused_auth; FolderNotFound ->
`carpeta <nombre> no encontrada`; SourceUnavailable -> error recorded, auto_sync untouched).

## Tests that look wrong (not edited)
1. `test_second_concurrent_sync_refused`: asserts `len(src.list_calls) == 1`, but `BlockingSource.list_ids`
   appends to `list_calls` and then calls `super().list_ids`, which appends again. One call always gives 2
   entries. Everything else in that test passes (second call refused, no extra fetches).
2. `test_first_sync_uses_30_day_window_...`: the fake has `respect_after=False` and still requires `"old"`
   (dated 31 days ago, but only known via the fake's metadata) never to be fetched. Sync cannot know a
   message date before fetching it, so no implementation can satisfy this. The window itself is correct
   (`list_calls[0][1] == today-30d`, backfill_from set).

## Differences from decisions.md (tests win)
- Summary has extra keys: `run_id` (test reads it), `notice`, and on refusal `message: "sync already running"`
  (test needs that exact string as a value; `error` stays None).
- Folder-not-found error code is `folder_not_found`; mailbox_state.last_error holds the Spanish text pinned by tests.
- Other last_error texts (Spanish, no secrets): auth revoked / source unavailable.

## Not covered by docs
- Oldest-first: `list_ids` returns "any order" and dates are unknown before fetching, so the source's order is
  kept (test_interruption requires the fake's order). GmailSource yields newest-first, so real syncs are not
  strictly oldest-first; a reviewer/user should decide (would need sort-by-fetch or a T057 change).
- Unexpected (non-source) exceptions: state and run marked failed, then re-raised.
- Missing mailbox_state row raises RuntimeError (misconfiguration).

## Gates
compileall ok. pytest -m "not slow": 530 passed, 2 failed (the two tests above), 1 skipped. anonymise --check: no output (no findings). Diff vs main: no forbidden paths; requirements.txt unchanged.
