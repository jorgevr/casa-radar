# Implementation Plan: Import Candidate Homes from Portal Alert Emails

**Branch**: `001-alert-email-import` | **Date**: 2026-10-23 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `/specs/001-alert-email-import/spec.md`

## Summary

The user supplies saved Idealista new-listing alert emails (`.eml` / `.mbox`, from a folder or the
UI). The tool stores every message in full, reads its listing blocks with a layout-specific reader
built only from real anonymised samples, records each appearance as a dated *sighting*, and merges
sightings into the existing candidate listings by Idealista listing code. Alerts never erase known
values or overwrite values the user entered, price history is dated by the alert, and unreadable
emails are reported with evidence. Ranking gains unknown-field flags, zone-not-recognised handling,
possible-duplicate flags and a scoring version. No network access during import, no new
dependencies. See [research.md](research.md).

## Technical Context

**Language/Version**: Python 3.11+ (existing app)

**Primary Dependencies**: existing only (FastAPI, uvicorn, PyYAML, pandas…). Email reading uses the
standard library (`email`, `mailbox`, `html.parser`). No new dependency.

**Storage**: existing local SQLite database (`data/casa.db`): new tables `import_runs`,
`alert_emails`, `sightings`; nullable columns added to `listings` ([data-model.md](data-model.md)).

**Testing**: pytest, offline; fixtures in `tests/fixtures/emails/`; outbound connections disabled
in import tests.

**Target Platform**: the user's Windows machine, local server on 127.0.0.1.

**Project Type**: single-user local web app + CLI (one Python package `app/`, one HTML page).

**Performance Goals**: 30 emails imported in < 5 s (SC-001).

**Constraints**: zero outbound requests during import; raw emails local only; no inference of
missing fields.

**Scale/Scope**: tens of emails per batch, a few hundred listings in total.

**Open (blocking one task group)**: the Idealista alert layout — see R2. Resolved only by real
samples, not by research.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

Mark each article pass / n/a / violation (see `.specify/memory/constitution.md`):

- [x] I Honest Data: **pass** — sightings carry source email and alert date; missing fields stay null
  and show "unknown"; hard filters on unknown fields flag instead of passing (R7); zone not guessed (R6)
- [x] II Estimates, Not Advice: **n/a** — no change to money outputs
- [x] III Local-First & Private: **pass after prerequisite P0** — no outbound endpoint added; import
  makes no requests (R14). **Found**: `data/casa.db` and `config/needs.yaml` are tracked by git;
  raw emails would enter the repository. P0 untracks them before any email is stored (R10)
- [x] IV Lawful Sourcing: **pass** — the user's own alert emails, supplied by the user; INE municipality
  list is official open data downloaded once by hand (R6); no crawling
- [x] V Human in the Loop: **pass** — no portal page or tracking link is ever opened (R3)
- [x] VI Fail Loudly: **pass with gate** — reader reports problems with evidence and never guesses
  ([alert-reader contract](contracts/alert-reader.md)); reader tasks blocked until samples exist (R2);
  all tests offline
- [x] VII Test-First Money Maths: **pass** — scoring changes (duplicate thresholds, unknown-field
  flags, zone-less medians) get golden tests with the hand calculation cited
- [x] VIII Explainable & Reproducible: **pass** — `SCORING_VERSION` introduced (= 2) and exported
  (R9); same-day price conflicts resolved independently of import order (R4)
- [x] IX Keep Raw Data: **pass** — every message stored in full with reader version; re-processing
  without the original file (R10)
- [x] X Simplicity & Time-Box: **pass** — no new dependency (R1, R12). v1 date still
  `TODO(V1_DATE)` in the constitution; this feature is on the v1 critical path (only discovery channel)

Post-design re-check (after Phase 1): unchanged; no violations to justify.

## Project Structure

### Documentation (this feature)

```text
specs/001-alert-email-import/
├── plan.md              # this file
├── research.md          # Phase 0
├── data-model.md        # Phase 1
├── quickstart.md        # Phase 1
├── contracts/
│   ├── alert-reader.md  # layout-specific reader contract
│   ├── cli.md           # import-emails, reprocess-emails
│   └── api.md           # local HTTP API used by the UI
└── tasks.md             # Phase 2 (/speckit-tasks)
```

### Source Code (repository root)

```text
app/
├── db.py                       # + new tables, nullable listing columns, idempotent migration
├── listings.py                 # + apply_sighting(): merge rules R4/R5, field_sources
├── scoring.py                  # + SCORING_VERSION, unknown-field flags, zone-less handling,
│                               #   duplicate flags, availability/merged handling
├── alerts.py                   # NEW generic layer: load .eml/.mbox, unwrap forwards, store
│                               #   alert_emails, call reader, map outcomes, write sightings, run summary
├── zones.py                    # NEW known-zone matching from config/zones_madrid_region.csv + districts
├── providers/
│   └── idealista_alert.py      # NEW layout-specific reader (BLOCKED until samples, R2)
├── cli.py                      # + import-emails, reprocess-emails
├── main.py                     # + /api/alerts/*, merge, availability, new_since_last_import
└── static/index.html           # + import emails (Datos), unknown fields, flags, merge, mark gone,
                                #   "new since last import" filter
config/
└── zones_madrid_region.csv     # NEW INE municipalities, province 28, with source + date
tests/
├── fixtures/emails/            # anonymised real samples (provided by the user)
├── test_core.py                # existing
├── test_alerts.py              # NEW import, dedup, history, failures, no-network, timing
├── test_idealista_alert.py     # NEW reader against each fixture (after samples)
├── test_scoring_v2.py          # NEW golden tests for scoring changes
└── test_fixture_privacy.py     # NEW FR-024 check
```

**Structure Decision**: keep the existing single package. The generic email layer (`alerts.py`) is
separate from the layout reader (`providers/idealista_alert.py`) so that everything except the reader
can be built and tested now, and future portals add one reader each.

## Delivery order

1. **P0 (prerequisite, Article III)**: untrack `data/` and add it to `.gitignore`; split personal values
   out of tracked `config/needs.yaml` (untracked local file, tracked example). Check whether earlier
   commits of `casa.db` hold personal data before pushing.
2. Storage + merge rules + scoring changes + generic email layer, tested with synthetic messages that
   exercise only generic behaviour (outcome mapping, dedup, dates, forwards wrapping per RFC 822),
   with the reader replaced by a stub that honours the contract.
3. **After samples exist**: the Idealista reader, written from the fixtures, plus fixture tests.
4. UI and CLI wiring; quickstart run.

## Complexity Tracking

No constitution violations to justify. No new dependencies.
