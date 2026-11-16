# T065 — quickstart.md sections 1–6 results

Branch `task/T065-quickstart`, base `9d7863c`. No code changes. Agent runs used the isolation env vars
(`CASA_DB`, `CASA_NEEDS`, `CASA_APPDATA` under `%TEMP%\casa-agent`); the agent did not touch the mailbox,
`data/`, real config or `%LOCALAPPDATA%\casa-radar\`.

| Section | Who ran it | Result | Evidence |
|---|---|---|---|
| 1. Offline test suite (incl. slow) | agent | PASS: 599 passed, 1 skipped, 0 failed | `python -m pytest -q`, run twice (483 s and 425 s). The skip is `tests/test_scoring_unknown.py:120` ("branch point not available"), not a failure. |
| 2. File import from CLI (fixtures only) | agent | PASS | First run: `12 emails: 11 importados, 0 ya procesados, 1 rechazado, 0 fallidos`; `anuncios: 11 nuevos, 0 actualizados (0 cambios de precio)`; the rejected one is the 2021 email, "tipo de alerta no soportado" (counts add up, SC-004). Second run: `12 emails: 0 importados, 12 ya procesados, 0 rechazados, 0 fallidos`; `anuncios: 0 nuevos` (SC-003). Wall time of the first CLI run, incl. Python start-up: 2.67 s (< 5 s, SC-001; the in-suite SC-001 test also passed). Per-listing published/history checks for 112842548, 112692121, 112658090 were not inspected by hand; they are covered by the derivation tests in section 1. |
| 3. Mailbox setup (real account) | user | user-attested | User reported they completed it on their real account. Agent did not run it. |
| 4. Ranked list (live parts) | user | user-attested | User reported they completed the live parts on their real account. Only reported problem: see known issue below. Agent did not open the UI against real data. |
| 5. Failure paths | user | user-attested | User reported they completed it. Agent did not run it. |
| 6. Clean up | agent | Done for agent artefacts | Only `%TEMP%\casa-agent` removed. The user's `data/casa.db` and Google permissions were not touched (user's call). |
| SC-008 (alert visible ≤ 16 min while app runs) | user | user-attested, no measurement recorded by agents | The user supplied no number. |

## Known issue

| Issue | Status | Regression test |
|---|---|---|
| UI did not react when clicking "Sincronizar ahora" after renewing the permissions (reported by the user) | fixed (user report) | None found that targets this bug. `grep` of `tests/` for the button text, `syncNow` and `/api/sync` matches nothing; the UI has no JS tests. The fix commit is not in this branch's history (HEAD is `9d7863c`; the last `app/static/index.html` change is `92a9c34`), so the agent could not inspect it. Backend endpoint behaviour is covered by `tests/test_api_mailbox.py` (`test_sync_returns_202_run_id_and_runs_in_worker`, `test_sync_409_while_running`, `test_sync_rejected_when_not_configured`, `test_sync_rejected_when_revoked`), but these predate and do not exercise the UI path. Reviewer: confirm where the fix lives and whether a test is wanted. |

## Gates

Only the handoff file was added; no `data/`, config, secrets or `.eml` changes; `requirements.txt` unchanged.
