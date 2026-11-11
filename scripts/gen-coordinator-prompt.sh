#!/usr/bin/env bash
# ==============================================================================
# gen-coordinator-prompt.sh
# Dynamic Prompt Generator for Orca Coordinator (casa-radar)
# Aligned with AGENTS.md (which overrides docs/agent-fleet.md).
# ==============================================================================
# Usage:
#   ./scripts/gen-coordinator-prompt.sh [options]
#
# Examples:
#   ./scripts/gen-coordinator-prompt.sh -f specs/001-alert-email-import -t "Phase 9: T050-T053" -b phase_9 -T
#   ./scripts/gen-coordinator-prompt.sh --interactive
# ==============================================================================

set -euo pipefail

# Defaults
PROJECT_NAME="casa-radar"
FEATURE_DIR=""
TASK_SCOPE=""
TARGET_BRANCH="spec-kit"
BASE_REF="main"
TIER_C_MODEL="ollama/qwen3"
# Gates from AGENTS.md "Doing a task" step 3 (no linter: Article X)
DEFAULT_GATES='python -m compileall -q app tests && python -m pytest -q -m "not slow" && python tests/fixtures/anonymise_eml.py --check tests/fixtures/emails'
STACK_GATES="$DEFAULT_GATES"
TESTS_ONLY=false
INTERACTIVE=false

usage() {
  cat <<HELP
Usage: $(basename "$0") [OPTIONS]

Options:
  -f, --feature-dir <path>     Path to spec directory (e.g. specs/001-alert-email-import)
  -t, --tasks <scope>          Task scope or group (e.g. "Phase 9: T050-T053")
  -b, --branch <name>          Branch the coordinator merges into (default: "spec-kit")
  -r, --base-ref <ref>         Ref for scope-guard diffs (default: "main")
  -p, --project <name>         Project name (default: "casa-radar")
  -m, --model-tier-c <model>   Tier C Ollama model, Reviewer only (default: "ollama/qwen3")
  -g, --gates <commands>       Deterministic gates (default: AGENTS.md gates)
  -T, --tests-only             Scope has only test tasks: skip the Developer stage
  -i, --interactive            Prompt interactively for inputs
  -h, --help                   Show this help message

HELP
  exit 0
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    -f|--feature-dir) FEATURE_DIR="$2"; shift 2 ;;
    -t|--tasks) TASK_SCOPE="$2"; shift 2 ;;
    -b|--branch) TARGET_BRANCH="$2"; shift 2 ;;
    -r|--base-ref) BASE_REF="$2"; shift 2 ;;
    -p|--project) PROJECT_NAME="$2"; shift 2 ;;
    -m|--model-tier-c) TIER_C_MODEL="$2"; shift 2 ;;
    -g|--gates) STACK_GATES="$2"; shift 2 ;;
    -T|--tests-only) TESTS_ONLY=true; shift ;;
    -i|--interactive) INTERACTIVE=true; shift ;;
    -h|--help) usage ;;
    *) echo "Unknown option: $1"; usage ;;
  esac
done

if [ "$INTERACTIVE" = true ] || [ -z "$FEATURE_DIR" ]; then
  echo "--- Interactive Coordinator Prompt Configuration ($PROJECT_NAME) ---"

  read -r -p "Feature directory [e.g., specs/001-alert-email-import]: " INPUT_FEATURE_DIR
  FEATURE_DIR="${INPUT_FEATURE_DIR:-specs/001-alert-email-import}"

  read -r -p "Task scope [e.g., Phase 9 (T050-T053)]: " INPUT_TASK_SCOPE
  TASK_SCOPE="${INPUT_TASK_SCOPE:-Phase 9}"

  read -r -p "Merge branch [default: $TARGET_BRANCH]: " INPUT_BRANCH
  TARGET_BRANCH="${INPUT_BRANCH:-$TARGET_BRANCH}"

  read -r -p "Tier C local model [default: $TIER_C_MODEL]: " INPUT_TIER_C
  TIER_C_MODEL="${INPUT_TIER_C:-$TIER_C_MODEL}"

  read -r -p "Deterministic gates [default: AGENTS.md gates]: " INPUT_GATES
  STACK_GATES="${INPUT_GATES:-$DEFAULT_GATES}"

  read -r -p "Tests-only scope? [y/N]: " INPUT_TO
  case "${INPUT_TO:-n}" in y|Y) TESTS_ONLY=true ;; esac
fi

# Derive Feature Title from spec.md if available
FEATURE_TITLE=""
if [ -f "$FEATURE_DIR/spec.md" ]; then
  FEATURE_TITLE=$(grep -m 1 "^# " "$FEATURE_DIR/spec.md" 2>/dev/null | sed 's/^# //' || true)
fi
if [ -z "$FEATURE_TITLE" ]; then
  FEATURE_TITLE=$(basename "$FEATURE_DIR")
fi

# Scope guard gates (AGENTS.md step 3)
DIFF_GATES="git diff --name-only ${BASE_REF}...HEAD   -> nothing under data/, no config/needs.yaml, config/zone_aliases.yaml,
        client_secret*, token*, and no .eml outside tests/fixtures/emails/
     git diff ${BASE_REF}...HEAD -- requirements.txt   -> must be empty"

# Stage 2 text depends on scope
if [ "$TESTS_ONLY" = true ]; then
  DEV_BLOCK="3. STAGE 2: DEVELOPER - SKIPPED (tests-only scope; implementation tasks are not in scope)
   - Instead, verify per task branch, stopping at the first failure:
     python -m compileall -q app tests
     python -m pytest --collect-only -q   (only the expected missing-module errors are acceptable)
     python tests/fixtures/anonymise_eml.py --check tests/fixtures/emails
     ${DIFF_GATES}
   - Commit locally, message 'T0NN: <summary>'. No Developer handoff file is needed."
  REPAIR_TARGET="the Test Author (same worktree, same task; the Reviewer never edits)"
  REPAIR_STAGES="Stages 1, 2 (verify) and 3"
else
  REPAIR_TARGET="the Developer (same worktree, same task; tests are never edited to pass)"
  REPAIR_STAGES="Stages 2-3"
  DEV_BLOCK="3. STAGE 2: DEVELOPER (Tier B - Cloud Coding)
   - Hand off the existing child worktree to the Developer:
     orca orchestration worker-start --task <taskId> --worktree current --agent claude --json
   - Implement minimal application logic until these pass, stopping at the first failure:
     ${STACK_GATES}
     ${DIFF_GATES}
   - Hot files (app/db.py, app/scoring.py, app/main.py, app/cli.py, app/static/index.html,
     app/derive.py, app/alerts.py, tests/conftest.py): one task at a time. If another task or
     worktree is editing one, stop and report.
   - No new dependency, no linter. A scoring change bumps SCORING_VERSION. Never edit tests.
   - Local commits only, message 'T0NN: <summary>'. Writes ${FEATURE_DIR}/handoffs/T0NN-dev.md
     (what changed, files, decisions the docs don't cover, what a reviewer should check).
     Does NOT edit tasks.md."
fi

cat <<EOF
============================= COPY TO ORCA COORDINATOR =============================
You are the Orca Coordinator for ${PROJECT_NAME}. Your mission is to implement and verify:
Feature: ${FEATURE_TITLE}
Directory: ${FEATURE_DIR}
Scope: ${TASK_SCOPE}. Work from this workspace root on branch '${TARGET_BRANCH}'.

Read first, in this order:
1. AGENTS.md
2. .specify/memory/constitution.md   (overrides everything, including AGENTS.md and docs/agent-fleet.md)
3. docs/agent-fleet.md
4. ${FEATURE_DIR}/tasks.md
If an instruction conflicts with the constitution, stop and ask me.

### Isolation (every worker session, before running anything)
PowerShell, from the worktree root:
  New-Item -ItemType Directory -Force "\$env:TEMP\\casa-agent" | Out-Null
  \$env:CASA_DB="\$env:TEMP\\casa-agent\\casa.db"
  \$env:CASA_NEEDS="\$env:TEMP\\casa-agent\\needs.yaml"
  \$env:CASA_APPDATA="\$env:TEMP\\casa-agent\\appdata"
  Copy-Item config\\needs.example.yaml \$env:CASA_NEEDS -Force
Do not run anything if any of the three is unset or points into the repository or the real app folder.

### Core Loop Protocol
Group tasks marked [P] that edit different files into ONE run (one run-create). Give each task its own
child worktree on branch task/T0NN-<slug> and run them in parallel. Tasks without [P], or with
"(depends on ...)", run after their dependency has merged. Never group two tasks that touch the same
hot file. Do exactly what each task says, in the files it names, nothing more.

1. INITIALIZE RUN & TASKS
   - Call: orca orchestration run-create --objective "Implement ${FEATURE_TITLE}: ${TASK_SCOPE}" --json
   - Per task:
     orca orchestration task-create --spec "<task_specification_from_tasks.md>" --task-title "<task_title>" --json
   - Save each returned taskId.

2. STAGE 1: TEST AUTHOR (Tier C - Local Ollama), one per task, in parallel
   - orca orchestration worker-start --task <taskId> --worktree new-child --name task-T0NN-<slug> --agent opencode --setup run --json
     (no --model: Orca refuses OpenCode model selection in a NEW worktree; OpenCode uses its own configured model.
      --model is only allowed on an existing worktree, so it is used for the Reviewer only.)
   - Tests only, written first. Forbidden from writing or modifying application logic in app/.
     Confirm they fail for the right reason (missing behaviour). A missing-module import error is
     accepted ONLY when the implementation task is outside this scope; do not create stubs in app/.
     Never weaken a test; if a test looks wrong, say so in the handoff and stop.
   - Tests are offline: use the no_network fixture. Money/scoring golden tests use hand-calculated
     expected values with the calculation and source in a comment. Parsers only from real fixtures.
   - Touch only the files the task names. Writes ${FEATURE_DIR}/handoffs/T0NN-tests.md
     (what each test asserts, files, decisions the docs don't cover).
   - Run: orca orchestration check --wait --types worker_done,escalation,question --timeout-ms 900000 --json

${DEV_BLOCK}

4. STAGE 3: REVIEWER (Tier C - Local Ollama, author != reviewer, read-only)
   - orca orchestration worker-start --task <taskId> --worktree current --agent opencode --model ${TIER_C_MODEL} --json
   - Evaluate the git diff against the acceptance criteria: edge cases, idempotency, secrets/PII leaks,
     OWASP top 10, no imputed values (absent = null/"desconocido", never "no"), no literals for rates/
     weights/thresholds, no network calls, no new dependency. Forbidden from modifying code.
   - Writes one file per task: ${FEATURE_DIR}/handoffs/T0NN-review.md with an explicit status [PASS] or
     [FAIL] and line-item notes (per-task files so grouped tasks never overwrite each other).

5. REPAIR LOOP & CIRCUIT BREAKER
   - On [FAIL]: feed that task's T0NN-review.md back to ${REPAIR_TARGET} and repeat ${REPAIR_STAGES}. Max 2 repair iterations per task; a failing task halts
     only that task, the others continue.
   - Halt and escalate with 'orca orchestration ask' if a gate or review fails twice, a test looks wrong,
     or a task needs a spec/plan change, a new dependency, a network call, a path under "Never read",
     or a fixture the docs don't cover.

6. DECISION GATE & MERGE
   - When the group's tasks are [PASS], open one approval gate:
     orca orchestration gate-create --task <taskId> --question "Tasks <ids> passed tests and review. Merge into ${TARGET_BRANCH}?" --options '["yes","no"]' --json
   - On approval, merge each task/T0NN-<slug> locally into '${TARGET_BRANCH}', release the worker panes
     (orca orchestration worker-release). Only the coordinator ticks the tasks in ${FEATURE_DIR}/tasks.md.

### Hard Safety Limits
- Never read, copy, print or upload: data/, config/needs.yaml, config/zone_aliases.yaml,
  %LOCALAPPDATA%\\casa-radar\\ . Never put secrets, tokens, personal data or a non-anonymised .eml in the
  repo, logs, test output or a handoff file.
- Never run mailbox-setup, a real sync, or authorise against Google. Never work in C:\\code\\casa-radar.
- Local commits only. Never push, force-push, rebase shared branches, rewrite history, or touch main.
- Agents pass context only through files, never through another agent's chat.
- Pilot rule: complete the whole [P] group end to end, then STOP and send me a summary report per task
  (gates passed, loop iterations used, files touched). Wait for my go-ahead before the next group.
====================================================================================
EOF
