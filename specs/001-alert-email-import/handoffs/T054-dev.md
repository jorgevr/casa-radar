# T054 dev handoff

Changed: created `app/mailbox/__init__.py` (only file touched, plus this handoff).
- `MailSource` as a `typing.Protocol` (runtime_checkable) with account, resolve_folder, list_ids, fetch_raw per contract.
- `AuthRevoked`, `FolderNotFound`, `SourceUnavailable`, `WrongFolder`: plain `Exception` subclasses (no shared base; the contract says these are the only errors handled).

Decisions not in docs: `specs/001-alert-email-import/decisions.md` does not exist in this worktree, so none applied. runtime_checkable added for convenience.

Reviewer: tests build errors with one positional string arg (works). Nothing network-related in this module.

Gates: see coordinator report (results below).

## Gate results
- compileall: pass
- pytest -m "not slow": 499 passed, 1 skipped, 33 failed. All 33 fail on missing later modules (app.mailbox.credentials T055, oauth T056, gmail T057, app.alerts_sync); none on T054 names.
- anonymise --check: no output, no error
- diff name check: only app/mailbox/__init__.py and this handoff; requirements.txt diff empty
