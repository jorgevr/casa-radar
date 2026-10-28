# AGENTS.md — casa-radar

Casa Radar is a single-user, local-first tool that ranks candidate homes for one household. It handles
personal finance data and a real mailbox, so the rules below are not optional.

## Authority and where things are

- `.specify/memory/constitution.md` (articles I–X) overrides everything else, including this file and
  `docs/agent-fleet.md`. If an instruction conflicts with it, stop and ask the user.
- Work comes from `specs/001-alert-email-import/`: `tasks.md` (what to do), `spec.md`, `plan.md`,
  `research.md`, `data-model.md`, `contracts/`, `quickstart.md`. Do what the task says, in the files it
  names, and nothing more.
- `docs/agent-fleet.md` is the coordinator's brief. Read it only if you are the coordinator.
- Code: one package `app/`, tests in `tests/`, UI in `app/static/index.html`. Python 3.11+, standard
  library plus `requirements.txt` only. UI text in Spanish; code, comments and commits in English.

## Never read, copy, print or upload

- `data/`, `config/needs.yaml`, `config/zone_aliases.yaml` (household data, raw emails).
- `%LOCALAPPDATA%\casa-radar\` (OAuth client secret and token).
- The user's mailbox: never run `mailbox-setup`, a real `sync`, or authorise against Google. The user does that.
- The main checkout `C:\code\casa-radar`: it is the user's; do not work there.
- Never put secrets, tokens, personal data or a non-anonymised `.eml` in the repository, logs, test
  output or a handoff file.

## Isolation: set before running anything

The app defaults to the user's real database, needs file and OAuth folder. In every session, before
running tests, the CLI or `serve`, point them at a temporary location outside the repository
(PowerShell, from the worktree root):

```powershell
New-Item -ItemType Directory -Force "$env:TEMP\casa-agent" | Out-Null
$env:CASA_DB="$env:TEMP\casa-agent\casa.db"
$env:CASA_NEEDS="$env:TEMP\casa-agent\needs.yaml"
$env:CASA_APPDATA="$env:TEMP\casa-agent\appdata"
Copy-Item config\needs.example.yaml $env:CASA_NEEDS -Force
```

Do not run anything if any of the three is unset or points into the repository or the real app folder.

## Rules for every change (constitution, in short)

- No imputed values: an absent attribute is null / "desconocido", never "no" (I).
- Rates, taxes, weights and thresholds live in config, never as literals in logic (II, VIII). A scoring
  change bumps `SCORING_VERSION`.
- Money and scoring changes need golden tests whose expected values are calculated by hand or from an
  independent source, with the calculation and source in a comment (VII). Never copy expected values
  from the code's own output.
- Parsers are built only from the real anonymised fixtures in `tests/fixtures/emails/`. Unexpected
  shapes fail with evidence, never guesses. Never invent an email format (VI).
- Tests are offline: use the `no_network` fixture. Never follow a link, open a portal page or download
  an image (IV, V). Outbound calls only to endpoints the docs allow.
- No new dependency and no linter without the user's approval (X).
- Never print, log or return secrets (III).

## Doing a task

1. **Tests first.** Write the task's tests, run them, and confirm they fail for the right reason
   (missing behaviour, not an import or syntax error). Then implement. Never edit or weaken a test to
   make it pass; if a test is wrong, say so in your handoff and stop.
2. **Touch only the files the task names.** These hot files are edited by one task at a time:
   `app/db.py`, `app/scoring.py`, `app/main.py`, `app/cli.py`, `app/static/index.html`, `app/derive.py`,
   `app/alerts.py`, `tests/conftest.py`. If another task or worktree is editing one, stop and say so.
3. **Gates before you report done** (worktree root, stop at the first failure; if a command doesn't
   exist yet because an earlier task isn't done, say so, don't skip it silently):
   - `python -m compileall -q app tests`
   - `python -m pytest -q -m "not slow"` (slow tests run at phase checkpoints)
   - `python tests/fixtures/anonymise_eml.py --check tests/fixtures/emails`
   - `git diff --name-only jorgevr/spec-kit...HEAD` lists nothing under `data/`, no `config/needs.yaml`,
     `config/zone_aliases.yaml`, `client_secret*`, `token*`, and no `.eml` outside `tests/fixtures/emails/`
   - `git diff jorgevr/spec-kit...HEAD -- requirements.txt` is empty
4. **`tasks.md`**: under a coordinator, do not edit it (the coordinator ticks tasks). If the user runs
   `/speckit-implement` directly, tick tasks as that command specifies.
5. **Handoff** (under a coordinator only): write `specs/001-alert-email-import/handoffs/T0NN-<tests|dev>.md`
   with what changed or what each test asserts, the files, decisions the docs don't cover, and anything
   a reviewer should check. Pass context only through files, never through another agent's chat.

## Git

Local commits only, message `T0NN: <summary>`. Under a coordinator, work on the task branch
`task/T0NN-<slug>`. Never push, force-push, rebase shared branches, rewrite history or touch `main`.

## Stop and ask the user when

- a gate fails twice, a test looks wrong, or a task needs a spec or plan change;
- a task needs a new dependency, a network call, or a path listed under "Never read";
- a fixture shows something the docs don't cover;
- anything irreversible: push, merge to `main`, real sync or authorisation.

v1 must be usable by 2026-11-28 (Article X): no scope beyond `tasks.md`.
