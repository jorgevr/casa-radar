# T018 dev: import_paths

File changed: `app/alerts.py` only (added `import mailbox`, `Path`, two reason constants, helpers and `import_paths`).

## What it does
- `import_paths(conn, paths, kind="file_cli")`: `start_run`, expand, read, sort, `process_message(origin="file")`, `finish_run`.
- Folders: non-recursive, only `*.eml` / `*.mbox` (case-insensitive suffix), sorted by name. Other files inside a folder are ignored.
- `.mbox`: `mailbox.mbox`, raw bytes via `get_bytes`, `file_name` = `name#index` (0-based).
- All messages from all files are sorted by `Date` (oldest first, via timestamp); no/invalid Date goes last (then process_message fails it with REASON_NO_DATE).
- Returns the `import_runs` row (run_id, kind, status, n_*, ...) without `notes`, plus `problems`
  `[{email_id, alert_date, subject, outcome, reason}]` (rejected and failed only; "already" is not a problem) and
  `notices` `[{email_id, alert_date, subject, text}]`.

## Decisions the docs don't cover
- A path with an unsupported extension (e.g. `.msg`) given explicitly counts as 1 found + 1 failed, problem
  outcome `failed`, `email_id` = file name, reason `unsupported file format: save as .eml`. Keeps sum = n_found.
- An unreadable `.mbox`/`.eml` (missing path, OS or mailbox error) is counted the same way, reason
  `unreadable file: expected an .eml or .mbox file`. A garbage `.mbox` that `mailbox` parses as zero messages
  contributes nothing (0 found); I did not special-case it.
- The two new reasons are in English (the spec text for .msg is English); other reasons are Spanish. The CLI/UI may translate.
- Unexpected exception in the loop: run is marked `failed` with only the exception class name (no data) and the exception is re-raised.
- Not-a-Date ordering for tz-naive dates uses local time; fine for ordering only.

## Reviewer checks
- Tests T016 untouched; all 4 pass (3 non-slow, 1 slow) and the non-slow suite is green (75 passed).
- Message/notice `email_id` may be `sha256:...` when there is no Message-ID.

## Loop 1 fix
- Review T016 blocking finding 1: an `.mbox` that yields zero messages is now counted as 1 found + 1 failed,
  problem outcome `failed`, `email_id` = file name, reason `no messages found in .mbox file (an .eml saved with
  an .mbox name is not valid mbox)` (`REASON_EMPTY_MBOX`). Implemented by raising `mailbox.Error` from `_read_file`
  and reusing the existing `_count_file_failure`/problems path. Supersedes the "contributes nothing" note above.
- Non-blocking finding 4a (missing path vs unsupported format) not done.
