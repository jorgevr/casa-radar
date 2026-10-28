# Agent Fleet — casa-radar

> **Operational brief for the Orca coordinator agent.** Give this file to the coordinator. It
> assigns work to worker agents and passes each one the role section it needs (§3). Rules here never
> override `.specify/memory/constitution.md`; where they seem to conflict, the constitution wins and
> the coordinator stops and asks the user.

## 1. Principles

1. **Procedural contracts over personas.** Each role has inputs, steps, outputs and a gate. No
   roleplay.
2. **Deterministic checks before LLM review.** Whatever a command can decide (§4) is decided by the
   command; a failing gate stops the loop before any review tokens are spent.
3. **Author ≠ reviewer.** The Reviewer runs in a fresh, stateless session that sees only the spec,
   the task and the diff — ideally on a different model family from the Developer.
4. **Tiers, not model names, in prompts.** Concrete models are set in the Orca workspace
   configuration (§2).
5. **One task group = one worktree.** Parallel work runs in separate git worktrees on separate
   branches; hand-offs are files, never chat history (§6).
6. **The user owns irreversible steps.** Agents never push, merge to `main`, rewrite history, run a
   real mailbox sync, or authorise against Google. They stop and ask.

## 2. Model tiers

| Tier | Use | Suggested (set in Orca config, not in prompts) |
|---|---|---|
| **A — Frontier reasoning** | Coordinator, Reviewer for security/money tasks, spec changes | Claude Opus 5.5 |
| **B — Coding** | Developer, Test Author | Claude Sonnet 5.5 |
| **C — Fast / cheap** | Reviewer for UI/docs-only tasks, summaries | Claude Haiku 5.5, or a local model |

Tier C is never used for: golden-value tests (Article VII), the alert reader, anything under
`app/mailbox/`, or reviewing those. Any tier sends code and anonymised fixtures to its provider;
that is acceptable (no personal data), but agents must never read the paths listed in §6.3.

## 3. Roles

```text
[Coordinator, Tier A]
   ├─ picks next task group from tasks.md ──> Test Author [B]  (tests only, must fail)
   ├─ tests committed ──────────────────────> Developer [B]    (code only, gates §4 green)
   ├─ gates green ──────────────────────────> Reviewer [A or C, fresh session, read-only]
   └─ review PASS ──> ticks tasks.md, reports to user; FAIL ──> back to Developer (max 2 loops)
```

The spec, plan and tasks already exist (`specs/001-alert-email-import/`), so there is no separate
Planner: spec changes go through the Spec Kit commands (`/speckit-clarify`, `/speckit-plan`,
`/speckit-tasks`) run by the coordinator **with the user**, never silently by a worker.

### 3.1 Coordinator (Tier A)

- **Input**: `specs/001-alert-email-import/{spec,plan,tasks,research,data-model,quickstart}.md`,
  `contracts/`, the constitution, `handoffs/` and `reviews/`.
- **Steps**:
  1. Follow the **phase order of `tasks.md`** (delivery order: P0 → file path → mailbox). Within a
     phase, group tasks into units of work: a test task plus the implementation tasks it covers.
  2. Run groups in parallel only if they are marked `[P]` **and** touch no common file. Always
     serialise tasks touching the hot files: `app/db.py`, `app/scoring.py`, `app/main.py`,
     `app/cli.py`, `app/static/index.html`, `app/derive.py`, `app/alerts.py`,
     `tests/conftest.py`. Test files are one per task in `tasks.md`; if two tasks name the same
     test file, serialise them too.
  3. For each group: create a worktree and branch `task/T0NN-<slug>` from the feature branch, give
     the Test Author §3.2, then the Developer §3.3, run §4, then give a fresh Reviewer §3.4.
  4. On PASS: merge the task branch into the feature branch (local merge only), tick the task
     boxes in `tasks.md` (only the coordinator edits `tasks.md`), and post a one-paragraph status
     to the user.
  5. Stop and ask the user when: a gate fails twice; the Reviewer fails a group twice; a task needs
     a spec/plan change; a task needs a new dependency (Article X); a phase checkpoint is reached
     (end of Phase 3, Phase 8 = 2026-11-14 target, Phase 9 = v1 2026-11-28).
- **Output**: updated `tasks.md`, one status message per merged group, checkpoint reports.

### 3.2 Test Author (Tier B)

- **Input**: the task IDs, `tasks.md`, the relevant contract and data-model sections,
  `tests/fixtures/emails/`, `tests/conftest.py`.
- **Steps**: write the test tasks of the group exactly as described; run them and confirm they fail
  for the right reason (missing function/behaviour, not import or syntax errors). Use the
  `no_network` fixture in every test that imports, syncs or uses the mailbox client.
- **Golden tests (Article VII)**: compute every expected money/score value by hand or from an
  independent source, and write the calculation and its source as a comment next to the assertion.
  Reader tests: read expected values from the fixture text by hand; never copy them from code
  output.
- **Constraints**: must not create or edit anything under `app/`; must not weaken an assertion to
  make it pass; must not invent email formats (Article VI) — only the 12 fixtures.
- **Output**: test files committed on the task branch; `handoffs/T0NN-tests.md` listing each test,
  what it asserts and why it fails now.

### 3.3 Developer (Tier B)

- **Input**: the task IDs, `tasks.md`, the failing tests, the contracts, research decisions cited
  in the task, `handoffs/T0NN-tests.md`.
- **Steps**: implement one task at a time, in the files the task names, matching the surrounding
  code style; run §4 after each task.
- **Constraints**:
  - must not edit the Test Author's tests; if a test is wrong, write it up in the handoff and stop;
  - no new dependency (Article X); standard library + `requirements.txt` only;
  - no network access at runtime except the endpoints in research R8, and none in tests;
  - never print, log or return secrets; never place secrets or personal data in the repository;
  - no literal tax/rate constants in logic (Article II); weights and thresholds in config (VIII).
- **Gate**: §4 green.
- **Output**: code committed on the task branch; `handoffs/T0NN-dev.md`: what changed, files,
  decisions not covered by the docs, anything the Reviewer should look at.

### 3.4 Reviewer (Tier A for Phases 2, 4, 5, 6, 9; Tier C allowed for UI/docs-only groups)

- **Runs in**: a fresh read-only session on the task worktree. Sees only: the task text, the cited
  spec/contract sections, the constitution, `git diff <feature-branch>...HEAD`, the §4 output and
  the two handoffs.
- **Checks**:
  1. every acceptance criterion of the tasks is met and tested;
  2. the constitution checklist in §5;
  3. edge cases named in the spec for these tasks; idempotency (re-import, re-sync, re-derive);
     order independence where `derive.py` is touched;
  4. security: secrets never logged/returned/committed, read-only Gmail scope, only allowed calls,
     no outbound request from tests, no path outside the configured label read;
  5. tests not weakened (compare with `handoffs/T0NN-tests.md`).
- **Constraints**: no code edits and no code suggestions beyond naming the problem; no style
  comments (out of scope).
- **Output**: `reviews/T0NN.md` starting with `STATUS: PASS` or `STATUS: FAIL`, then numbered
  findings with file:line and the criterion or article they break.

## 4. Deterministic gates

Run from the worktree root, in this order; stop at the first failure. Every agent session (and
every gate run) first sets the isolation variables of §6.3, e.g. in PowerShell:
`$env:CASA_DB="$env:TEMP\casa-agent\casa.db"; $env:CASA_NEEDS="$env:TEMP\casa-agent\needs.yaml";
$env:CASA_APPDATA="$env:TEMP\casa-agent\appdata"` (copy `config/needs.example.yaml` to the
`CASA_NEEDS` path first).

| Gate | Command | Pass when |
|---|---|---|
| Isolation | check that `CASA_DB`, `CASA_NEEDS`, `CASA_APPDATA` are set and none points into the repository or the real `%LOCALAPPDATA%\casa-radar` | all three set, all outside |
| Byte-compile | `python -m compileall -q app tests` | exit 0 |
| Test suite | `python -m pytest -q -m "not slow"` | exit 0, no skipped tests added by this task |
| Slow tests (checkpoints only) | `python -m pytest -q -m slow` | exit 0; run by the coordinator at each phase checkpoint, not per task (SC-001, SC-010 timings) |
| Fixture privacy (FR-024) | `python tests/fixtures/anonymise_eml.py --check tests/fixtures/emails` | exit 0 |
| Forbidden paths | `git diff --name-only <feature-branch>...HEAD` | lists nothing under `data/`, no `config/needs.yaml`, `config/zone_aliases.yaml`, `client_secret*`, `token*`, and no `.eml` outside `tests/fixtures/emails/` |
| No new dependency | `git diff <feature-branch>...HEAD -- requirements.txt` | empty, unless the user approved it |

No linter is part of the gate: adding one (e.g. ruff) is a new dependency and needs the user's
approval under Article X.

## 5. Constitution checklist for the Reviewer

- **I Honest Data**: no imputed values; absent attribute = null/"desconocido", never "no"; flags
  name what is missing.
- **II Estimates**: money outputs labelled as estimates; rates only from `needs.yaml`.
- **III Local-First**: no telemetry, no outbound call except research R8 endpoints; secrets only in
  the app folder; nothing personal in the repo.
- **IV Lawful Sourcing**: no portal page, tracking link or image requested; Gmail ≤ 10 req/s.
- **V Human in the Loop**: nothing follows links.
- **VI Fail Loudly**: unexpected shapes produce failures with evidence; parsers only from fixtures;
  tests offline.
- **VII Test-First Money Maths**: golden tests with cited hand calculation for every scoring/money
  change.
- **VIII Reproducible**: same inputs → same output; `SCORING_VERSION` bumped if scoring changed.
- **IX Keep Raw Data**: raw email stored before derivation; re-derivable.
- **X Simplicity**: no new dependency; smallest change that meets the task.

## 6. Workflow rules

### 6.1 Hand-offs

Agents pass context only through files in `specs/001-alert-email-import/`:
`handoffs/T0NN-tests.md`, `handoffs/T0NN-dev.md`, `reviews/T0NN.md`. They never read another
agent's chat. Hand-off files are committed with the task branch.

### 6.2 Directory scopes

- Coordinator: feature worktree (`jorgevr/spec-kit`), read access to all of it.
- Test Author, Developer, Reviewer: their task worktree only.
- The main checkout `C:\code\casa-radar` is the user's; no agent works there.

### 6.3 Never read, copy or upload

The app defaults to these real locations, so agents MUST always run with `CASA_DB`, `CASA_NEEDS`
and `CASA_APPDATA` pointing to a temporary folder (§4), including when they run the CLI or
`serve`. Without them, `serve` would use the user's real database and, after Phase 9, their real
OAuth authorisation.

- `data/` (local database with raw emails and listings);
- `config/needs.yaml` and `config/zone_aliases.yaml` (household data);
- `%LOCALAPPDATA%\casa-radar\` (OAuth client secret and token);
- the user's mailbox (agents never run `mailbox-setup` or a real `sync`; quickstart §3 and §5 are
  done by the user).

### 6.4 Git

Local commits on task branches; local merges into the feature branch by the coordinator. Never push,
force-push, rebase shared branches, rewrite history, or touch `main`. Commit messages:
`T0NN: <summary>`.

## 7. Rollout

1. **Phase 1 (now)**: Coordinator + Developer + Reviewer on Tier A/B for tasks.md Phases 1–3;
   tests written by the Developer but committed before the code. Measure: loops per group, gate
   failures.
2. **Phase 2**: split the Test Author out for Phases 4–8 (the golden-test heavy part).
3. **Phase 3**: allow Tier C reviewers for UI/docs-only groups if Phase 1–2 reviews were reliable.
