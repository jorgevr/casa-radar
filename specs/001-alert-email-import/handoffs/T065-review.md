# T065 review

**[PASS]** (with one non-blocking note, R5). Reviewer re-ran everything offline with `CASA_DB`, `CASA_NEEDS`,
`CASA_APPDATA` under `%TEMP%\casa-rev`; only `tests/fixtures/emails` was used.

## Line items

- **[PASS] Scope.** `git diff --name-only 9d7863c...HEAD` lists only
  `specs/001-alert-email-import/handoffs/T065-quickstart.md`. Merge base with `main` is `9d7863c`.
- **[PASS] R1 sections 1–6 covered.** `T065-quickstart.md:7-15` has a row for each of sections 1–6 plus SC-008,
  each with a "Who ran it" column: 1, 2 and 6 = agent; 3, 4, 5 and SC-008 = user.
- **[PASS] R1 user-attested items are not dressed up.** `T065-quickstart.md:11` "user-attested … Agent did not run
  it."; `:12` "Agent did not open the UI against real data."; `:13` "user-attested"; `:15` "user-attested,
  no measurement recorded by agents | The user supplied no number." No invented numbers or evidence.
- **[PASS] R2 section 1.** I ran `python -m pytest -q`: `599 passed, 1 skipped, 1 warning in 364.74s`. The
  handoff (`:9`) says "599 passed, 1 skipped, 0 failed" (483 s and 425 s). The counts match exactly; the times differ
  by machine load. The skip is real: `tests/test_scoring_unknown.py:120` is
  `pytest.skip("branch point not available")`, reached when `git merge-base HEAD jorgevr/spec-kit-3-feature` fails
  (line 118-120). No test-count gap, so no later-merge difference to explain.
- **[PASS] R2 section 2.** First run printed `12 emails: 11 importados, 0 ya procesados, 1 rechazado, 0 fallidos`,
  `anuncios: 11 nuevos, 0 actualizados (0 cambios de precio)`, `RECHAZADO 2021-03-10 … tipo de alerta no soportado`,
  exit 0, 1.80 s wall time (handoff `:10` says 2.67 s; both < 5 s). Second run:
  `12 emails: 0 importados, 12 ya procesados, 0 rechazados, 0 fallidos`, `anuncios: 0 nuevos`. This matches
  handoff `:10`. `anonymise_eml.py --check tests/fixtures/emails` returns rc=0.
- **[PASS] R3 vs quickstart/contract.** `quickstart.md:41-44` expects "12 emails = 11 imported + 1 rejected (2021
  layout…)" and "Second run: 12 already processed, 0 new listings". The CLI output matches. The line format
  matches `contracts/cli.md:42-43` (`N emails: … importados, … ya procesado(s), … rechazado(s), … fallido(s)` /
  `anuncios: … nuevos, … actualizados (… cambios de precio)`). Commands match `quickstart.md:37-38` and
  `cli.md:23` (`import-emails PATH`).
- **[PASS] R3 extra check beyond the handoff.** The handoff (`:10`) says the per-listing checks were not
  inspected by hand. I did: 112842548, 112692121 and 112658090 have `published_at` NULL and `price_history`
  rows with origin `alert_previous` plus `alert` (e.g. 112842548: 670000 → 645000 on 2026-10-26). This matches
  `quickstart.md:42-44`. The handoff's wording is accurate and conservative, so the omission is not an error.
- **[PASS] R4 privacy.** The handoff holds no emails, tokens, account names, paths under the user profile or
  listing content. Only the fixture counts and the "tipo de alerta no soportado" message appear. The diff touches no
  `data/`, config, `.eml` or `requirements.txt` file.
- **[PASS] R5 known issue, honest about location.** `T065-quickstart.md:21` says the fix is not in this
  branch and that no test targets it. Verified:
  - `app/static/index.html:345` has `async function syncNow(){if(syncBusy||(mbx&&mbx.running))return;syncBusy=true;
    drawMbx(); …`, with `:325` rendering the "Sincronizar ahora" button and `:326` `$('#mbsync').onclick=syncNow;`.
    Last change to the file in this branch: `92a9c34 T061: authorise before label in the Buzón card (N1)`, as the
    handoff says.
  - `grep -i "syncNow\|Sincronizar\|api/sync" tests` matches nothing. So no UI regression test exists, as the
    handoff states.
  - Nothing in this branch is labelled as the fix. The only candidate is the existing `syncNow` code, which could
    have the old behaviour. The fix therefore lives in the user's main checkout (not inspected, per rules) or is
    unmerged. Backend tests named in `:21` exist; I did not check each name.
- **[NOTE] R5 follow-up (non-blocking).** The fix is unverifiable from this branch and has no regression test. The
  coordinator should either merge the user's fix and add a test, or accept the user's attestation. I recommend
  recording a task for this.

## Gates run by reviewer
`pytest -q` 599 passed / 1 skipped; fixture `--check` rc=0; diff against `9d7863c` is a single handoff file.
I did not run `compileall` separately because pytest imports the whole package.
