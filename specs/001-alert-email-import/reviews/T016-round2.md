STATUS: PASS

Second review of T016 (tests) + T018 (`import_paths`), diff `jorgevr/spec-kit-2...HEAD` (head eaef02a).
Coordinator gates accepted as given. I also re-ran `pytest -q -m "not slow"` (78 passed) and
`tests/test_alerts_import.py` (7 passed, slow test included) with the isolation variables pointing at
`%TEMP%\casa-agent-T016R2`. I checked behaviour with an offline probe script kept outside the repository,
against in-memory databases. Nothing in the worktree was modified except this new file.

## (1) Review 1 blocking finding 1: resolved

`app/alerts.py:177-178` raises `mailbox.Error(REASON_EMPTY_MBOX)` when an `.mbox` yields no messages.
`app/alerts.py:209-214` counts that file as 1 found + 1 failed and adds a `failed` problem whose `email_id`
is the file name. Probe results, as (found, imported, already, rejected, failed):

| Case | Result | Sum = found | Run status |
|---|---|---|---|
| fixture `.eml` renamed to `.mbox` | (1,0,0,0,1), one problem | yes | `ok`, finished |
| empty `.mbox` | (1,0,0,0,1), one problem | yes | `ok`, finished |
| whitespace-only `.mbox` / binary junk `.mbox` | (1,0,0,0,1) each | yes | `ok` |
| explicit paths: renamed + empty + valid 2-message mbox + sibling `.eml` | (5,3,0,0,2), 2 problems, 3 rows | yes | `ok` |
| folder holding the same mix (empty, renamed, `.eml`, 2-message mbox) | (5,3,0,0,2) | yes | `ok` |
| missing `nope.mbox` | (1,0,0,0,1), `unreadable file…` | yes | `ok` |

No case marks the run `failed`, and the valid siblings are imported in the same call. None of the fixtures
contains a line starting `From `, so a renamed fixture cannot be split into fake messages.

## (2) Acceptance criteria and Loop 1 tests

All criteria from review 1's table still hold (fixture folder 12/11/0/1/0, 11 listings with price,
area-or-development and link, re-import all `already`, 3-message mbox imports 3, `.msg` reported
"unsupported file format: save as .eml", slow timing test). The original T016 tests are unchanged against
`handoffs/T016-tests.md`.

The Loop 1 tests (`tests/test_alerts_import.py:106-122`, `:125-136`) are legitimate. The expected counts are
derived by hand (one file = one found = one failed). The reason wording is not pinned: only a non-empty string
is required. Outcome, `email_id` = file name, no rows and sum = found are asserted. The handoff records that
they failed before the fix for the right reason (`n_found` 0). The non-recursion test guards part of review 1
finding 4. Neither test is over-fitted to the implementation.

## Findings

1. **Non-blocking. `app/alerts.py:172-174`: content before the first `From ` line of an otherwise valid
   `.mbox` is still dropped without a word (Article VI, SC-004).** Review 1 finding 1 noted this in passing.
   It is not made worse by this change. Probe: an `.eml` concatenated in front of a valid 1-message mbox gives
   (1,1,0,0,0) and no problem. The leading email is not in the summary. Real mbox exports (Gmail Takeout,
   Thunderbird) start with `From `, so this only affects files assembled by hand. The headline case (the whole
   file is not mbox) is now reported. The user should decide whether this residual case matters.

Review 1 non-blocking items 2, 3, 5 and 6 are unchanged and not made worse. Item 4 is partly addressed by
the non-recursion test. Ordering and the exact `#index` mapping are still untested.

## Constitution checklist (§5)

- I Honest Data: nothing imputed. Problems for unreadable files carry `alert_date`/`subject` = null.
- II Estimates / VII Money maths: not touched.
- III Local-First / security: no outbound call. Problems carry only the file name (not the path). The new
  reason is a fixed constant with no file content. Exception text is still class-name only. No secrets.
- IV / V: no link followed and no image fetched. All new tests use `no_network`.
- VI Fail Loudly: zero-message mbox files are now failures with evidence. See finding 1 for the residual case.
- VIII Reproducible: deterministic ordering is unchanged.
- IX Keep Raw Data: unchanged. Raw bytes go through `process_message`, and re-import is idempotent and tested.
- X Simplicity: standard library only. `requirements.txt` unchanged. The diff touches only `app/alerts.py`,
  `tests/test_alerts_import.py`, handoffs and reviews.

No regressions: the full non-slow suite passes, and the only warning is a third-party `pytz` deprecation
unrelated to this diff.
