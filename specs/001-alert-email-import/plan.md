# Implementation Plan: Import Candidate Homes from Portal Alert Emails

**Branch**: `001-alert-email-import` (worktree branch `jorgevr/spec-kit`) | **Date**: 2026-10-28 |
**Spec**: [spec.md](spec.md)

**Input**: Feature specification from `/specs/001-alert-email-import/spec.md`. This plan replaces the
file-only plan of 2026-10-23.

## Summary

Casa Radar reads Idealista alerts directly from one Gmail label, through Google's read-only,
user-revocable permission (`gmail.readonly`), every 15 minutes while the app runs and on demand;
`.eml`/`.mbox` import stays as a secondary path into the same pipeline. Every message is stored in
full locally; a layout reader written from the 12 real samples turns new-listing and price-drop
alerts into dated *sightings*; listing values, price history, published and updated dates and
"found via" categories are re-derived from all sightings, so the result never depends on
processing order. Developments become one candidate kept out of affordability until the user picks
a unit. Scoring gains unknown-field flags, zone-less handling, duplicate flags and a version number.
No new dependency: OAuth and Gmail calls use `httpx` and the standard library. See
[research.md](research.md).

## Technical Context

**Language/Version**: Python 3.11+ (existing app)

**Primary Dependencies**: existing only (FastAPI, uvicorn, httpx, PyYAML, pandas). Email parsing
with `email`, `mailbox`, `html.parser`; OAuth loopback with `http.server`, `webbrowser`,
`secrets`; token encryption with Windows DPAPI via `ctypes` (R3, R4).

**Storage**: local SQLite `data/casa.db` (untracked after P0): new tables `import_runs`,
`alert_emails`, `sightings`, `mailbox_state`; nullable columns on `listings` and `price_history`
([data-model.md](data-model.md)). Authorisation in `%LOCALAPPDATA%\casa-radar\`, outside the repo.

**Testing**: pytest, fully offline: fixtures in `tests/fixtures/emails/`, a fake `MailSource`,
`httpx.MockTransport` for the Gmail/OAuth client, socket creation disabled in import/sync tests.

**Target Platform**: the user's Windows 11 machine; local server on 127.0.0.1.

**Project Type**: single-user local web app + CLI (package `app/`, one HTML page).

**Performance Goals**: 30 files < 5 s (SC-001); new alert visible ≤ 16 min (SC-008); 1,000-email
backlog < 10 min with the UI usable (SC-010).

**Constraints**: only Google OAuth/Gmail endpoints contacted, only during setup/sync (R8); no
mailbox changes possible (read-only scope); ≤ 10 requests/s; raw emails local only; no inference
of missing fields.

**Scale/Scope**: a few alerts a day, tens of thousands of messages over years at most; a few
hundred listings.

No open NEEDS CLARIFICATION: the spec has none, and the layout questions are answered by the
samples (R9).

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

Mark each article pass / n/a / violation (see `.specify/memory/constitution.md`, v1.1.0):

- [x] I Honest Data: **pass** — each listing figure carries its sighting (email, alert date); absent
  attributes stay null and show "unknown", never "no" (R9); hard filters on unknown fields flag
  (R14); zones are never guessed (R10); development prices are labelled and not used as unit prices
  (R13); published/updated dates are "unknown" when no alert gives them (FR-036).
- [x] II Estimates, Not Advice: **pass** — no new money logic; the new-build flag from a category is
  shown next to the cost estimate it changes (FR-033); rates stay in `needs.yaml`.
- [x] III Local-First & Private: **pass after P0** — endpoints and fields sent listed in R8, none
  carries the tool's data. Mail provider: permission `gmail.readonly` (read-only is enough: the
  tool only lists and reads); limit to one label enforced on every call and re-checked per message
  (R1, mail-source contract); no mailbox changes possible; authorisation stored DPAPI-encrypted in
  `%LOCALAPPDATA%\casa-radar\`, outside the repository, and `client_secret*.json`/`token*.json`
  ignored (R4). **Blocking finding**: `data/casa.db` and `config/needs.yaml` are tracked by git;
  P0 fixes it before any email is stored (R16).
- [x] IV Lawful Sourcing: **pass** — the user's own mailbox under Google's API terms; access by the
  user's own OAuth client; ≤ 10 requests/s, sequential, stop on 429 (R7). INE municipality list is
  official open data, downloaded once by hand. No portal page is fetched.
- [x] V Human in the Loop: **pass** — no portal link, tracking link or image is ever requested
  (R9, FR-014); data comes only from emails the portal sent to the user.
- [x] VI Fail Loudly: **pass** — reader built from the 12 samples, which are in the repository
  anonymised (R9, R17); unknown layouts and mismatched prices fail with evidence; unknown attribute
  tokens are reported; sync failures stop with the reason; tests never reach Google.
- [x] VII Test-First Money Maths: **pass** — scoring changes (duplicate thresholds, unknown-field
  flags, zone-less medians, development exclusions, new-build flag on costs) get golden tests with
  the hand calculation cited next to them.
- [x] VIII Explainable & Reproducible: **pass** — `SCORING_VERSION` 1 → 2, returned and exported
  (R14); listing values derived from sightings independent of order, ties broken deterministically
  (R11); category rules in configuration.
- [x] IX Keep Raw Data: **pass** — every message stored as received with origin, fetch time and
  reader version; re-processing and category changes work from stored emails (R16).
- [x] X Simplicity & Time-Box: **pass** — no new dependency; Google client libraries rejected in R3
  (about eight packages for seven HTTP calls), `keyring` rejected in R4. v1 date **2026-11-28**
  (constitution v1.1.1); this feature is on the v1 critical path (the only discovery channel).
  v1 impact: the file path (delivery step 2) is targeted for 2026-11-14 and is usable on its own;
  mailbox sync (step 3) for 2026-11-28. If step 3 slips, v1 ships with file import and sync follows,
  rather than moving the date.

Post-design re-check (after Phase 1): unchanged. No violations to justify.

## Project Structure

### Documentation (this feature)

```text
specs/001-alert-email-import/
├── plan.md              # this file
├── research.md          # Phase 0
├── data-model.md        # Phase 1
├── quickstart.md        # Phase 1
├── contracts/
│   ├── alert-reader.md  # layout reader contract
│   ├── mail-source.md   # mailbox access interface + Gmail rules + authorisation flow
│   ├── cli.md           # mailbox-setup, sync, import-emails, reprocess-emails, categories
│   └── api.md           # local HTTP API used by the UI
├── tasks.md             # Phase 2 (/speckit-tasks)
├── handoffs/            # agent hand-off notes (docs/agent-fleet.md §6.1)
└── reviews/             # reviewer verdicts (docs/agent-fleet.md §3.4)
```

### Source Code (repository root)

```text
app/
├── db.py                     # + new tables/columns, idempotent migration
├── listings.py               # + field_sources on manual/CSV writes
├── alerts.py                 # NEW pipeline: parse/unwrap, store alert_emails, call reader,
│                             #   outcomes, sightings, run summaries (sync and files share it)
├── derive.py                 # NEW listing values, price history, dates, flags from sightings (R11)
├── categories.py             # NEW rules load/save, subject → category, re-derivation (R12)
├── zones.py                  # NEW municipality/district matching + user aliases (R10)
├── alerts_sync.py            # NEW sync loop: window, incremental, lock, schedule, state (R5, R6)
├── mailbox/
│   ├── __init__.py           # MailSource protocol + errors (contract)
│   ├── gmail.py              # NEW Gmail REST client over httpx (R1, R3, R7)
│   ├── oauth.py              # NEW installed-app flow: PKCE, loopback, refresh (R2, R3)
│   └── credentials.py        # NEW app folder, DPAPI encrypt/decrypt, redacted holder (R4)
├── providers/
│   └── idealista_alert.py    # NEW layout reader (R9)
├── scoring.py                # + SCORING_VERSION, unknown flags, zone-less medians,
│                             #   developments, duplicates, availability/merge
├── main.py                   # + /api/mailbox/*, /api/runs, /api/alerts/*, /api/categories,
│                             #   lifespan scheduler, listing PATCH/merge additions
├── cli.py                    # + mailbox-setup, sync, import-emails, reprocess-emails, categories
└── static/index.html         # + sync status bar and warning, Datos: mailbox setup, file import,
                              #   categories, failed emails; Oportunidades: dates columns + sort,
                              #   found via, unknown fields, development label, merge, mark gone
config/
├── alert_categories.yaml     # NEW rules (tracked)
├── zones_madrid_region.csv   # NEW INE province 28 (tracked, with source and date)
├── zone_aliases.example.yaml # NEW (real file untracked)
└── needs.example.yaml        # NEW (P0; needs.yaml untracked)
tests/
├── fixtures/emails/          # 12 anonymised samples (done)
├── fixtures/anonymise_eml.py # anonymiser + check (done)
├── test_core.py              # existing
├── test_fixture_privacy.py   # NEW FR-024
├── test_idealista_alert.py   # NEW reader per fixture
├── conftest.py               # NEW shared fixtures; autouse temp CASA_DB/CASA_NEEDS/CASA_APPDATA;
│                             #   no_network; marker slow (timing tests, run at checkpoints)
├── test_alerts_*.py, test_api_alerts.py      # NEW pipeline, outcomes, failures, new-since
├── test_derive*.py, test_availability.py     # NEW order independence, prices, dates, user values
├── test_mailbox_*.py         # NEW credentials, OAuth, Gmail client on MockTransport
├── test_sync.py              # NEW sync loop with fake MailSource
└── test_scoring_*.py         # NEW golden tests (one file per scoring change)
```

**Structure Decision**: keep the single `app/` package. Mailbox access sits behind the
`MailSource` contract so the sync loop is tested with fixtures and a second provider (or IMAP) would
be one new module. The reader is the only layout-specific code.

## Delivery order

1. **P0 (prerequisite, Article III)**: done on 2026-10-28 (staged): `data/` and `config/needs.yaml`
   untracked and ignored, `config/needs.example.yaml` tracked; history checked, only nulls and
   "EJEMPLO" rows, no rewrite needed; original samples moved out of the main checkout. Remaining
   code task: when `config/needs.yaml` is missing, the app copies it from `needs.example.yaml`
   (a fresh clone would otherwise fail to start).
2. **File path, usable on its own**: storage, reader, derivation, categories, zones, scoring v2,
   `import-emails`, UI columns and sorting. Tested with the fixtures.
3. **Mailbox**: secrets, OAuth, Gmail client, sync loop and schedule, status UI, setup screen.
4. Quickstart run on the real account.

## Complexity Tracking

No constitution violations to justify. No new dependencies (alternatives rejected in R3, R4).
