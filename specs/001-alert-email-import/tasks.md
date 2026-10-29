---

description: "Task list for 001-alert-email-import"
---

# Tasks: Import Candidate Homes from Portal Alert Emails

**Input**: Design documents from `specs/001-alert-email-import/` — [plan.md](plan.md),
[spec.md](spec.md), [research.md](research.md), [data-model.md](data-model.md),
[contracts/](contracts/), [quickstart.md](quickstart.md)

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/ (all present)

**Tests**: included. The constitution requires offline fixture tests for parser changes (VI) and
golden-value tests with a cited source for scoring changes (VII); the spec's Independent Tests and
the quickstart define the rest. Within each phase, write the tests first and see them fail.

**Organization**: phases follow the user's **delivery order**, not story priority:
P0 → file path (usable on its own, target 2026-11-14) → mailbox sync (target 2026-11-28, v1 date).
US1 (P1, mailbox) is therefore split: its category part (works with files) is Phase 5, its mailbox
part is Phase 9. Every task keeps its story label for traceability.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: can run in parallel (different files, no dependency on an incomplete task)
- **[Story]**: US1–US6 from spec.md
- Paths are relative to the repository root (single package `app/`, tests in `tests/`)

## Conventions for every task

- Python 3.11+, standard library + existing dependencies only (no new package, plan R3/R4).
- UI text in Spanish, like the existing UI and CLI; code and comments in English, matching the
  existing style (short module docstrings, few comments).
- No test may open a network connection: use the `no_network` fixture (T005) in every test that
  imports, syncs or talks to the mailbox client.
- Fixtures: `tests/fixtures/emails/*.eml` (12 anonymised alerts, see research R9 for what each
  contains). Never add a non-anonymised email; run `python tests/fixtures/anonymise_eml.py --check
  tests/fixtures/emails` before committing fixtures.

---

## Phase 1: Setup — P0 and shared configuration

**Purpose**: Article III prerequisite and static configuration all later phases use.

- [x] T001 Untrack `data/casa.db` and `config/needs.yaml`, add `data/`, `config/needs.yaml`, `config/needs.yaml.bak`, `config/zone_aliases.yaml` to `.gitignore`, add tracked `config/needs.example.yaml` (done 2026-10-28, staged)
- [x] T002 Move the original non-anonymised samples out of `C:\code\casa-radar\tests\fixtures\emails\` (done by the user)
- [X] T003 In `app/db.py`, make `load_needs()` copy `config/needs.example.yaml` to `config/needs.yaml` when the latter is missing (fresh clone), and change `NEEDS` in `tests/test_core.py` to load `config/needs.example.yaml` so tests never depend on the user's personal file
- [X] T004 [P] **User step first, then agent.** (a) *User*: download INE "Relación de municipios y sus códigos por provincias" (current year, official file from ine.es, one manual download) and save it as `config/source/ine_municipios.xlsx`, noting its URL and download date in `config/source/README.md`. (b) *Agent*: convert it, with the existing pandas/openpyxl, into `config/zones_madrid_region.csv` with columns `ine_code,municipality,source,as_of` — exactly the 179 rows of province 28, `source` and `as_of` from that README (no network access by the agent); also create `config/zone_aliases.example.yaml` with a commented example `"alto de San Isidro, San Isidro, Madrid": madrid/carabanchel`
- [X] T005 [P] Create `tests/conftest.py` with fixtures: `conn` (in-memory db + `seed_madrid_districts`, same as test_core), `needs` (from `config/needs.example.yaml`), `fixture_emails` (sorted list of `tests/fixtures/emails/*.eml` paths), `no_network` (monkeypatch `socket.socket.connect` and `socket.create_connection` to raise `AssertionError("network access in test")`), an **autouse** fixture `isolated_paths` setting `CASA_DB`, `CASA_NEEDS` (copy of `needs.example.yaml`) and `CASA_APPDATA` to `tmp_path` locations so no test can touch `data/`, `config/needs.yaml` or `%LOCALAPPDATA%\casa-radar\`, and register the marker `slow` in `pytest_configure` (`slow` tests are excluded from the per-task gate and run at checkpoints)
- [X] T006 [P] Create `config/alert_categories.yaml` with rules `obra nueva en tu zona personalizada → new-build`, `chalets en tu zona personalizada → house`, `apartamentos en tu zona personalizada → flat` (format: list of `{contains, category}`; comment that the old name `Viviendas en tu zona personalizada` covered two searches and has no rule on purpose, research R12)
- [X] T007 [P] Add `tests/test_fixture_privacy.py`: load `tests/fixtures/anonymise_eml.py` by path with `importlib.util.spec_from_file_location` (the folder is not a package), call `check(Path("tests/fixtures/emails"))` and assert it returns True; also assert there are ≥ 12 fixtures (FR-024)

**Checkpoint**: `python -m pytest -q` passes on a clean clone with no `config/needs.yaml`.

---

## Phase 2: Foundational — storage, reader, pipeline core, derivation core, zones

**Purpose**: everything any alert listing needs to exist. Blocks all story phases.

### Tests first

- [X] T008 [P] Add `tests/test_idealista_alert.py`: for each fixture assert the exact `ReadResult` per [contracts/alert-reader.md](contracts/alert-reader.md) — alert type, search name, listing code, price, previous price (price drops), area, bedrooms, floor, exterior/elevator/garage (True or None, never False), type text and mapped type, development flag, location text, direct link `https://www.idealista.com/inmueble/<code>/` or `/obra-nueva/<code>/`, no problems. Expected values come from reading each fixture by hand (write them in the test as literals). The 2021 fixture must give `unsupported`. Add negative cases built by editing a fixture in memory: two distinct listing codes → problem; price drop with card price ≠ "a <new>€" → problem; an extra attribute token "2 baños" → notice, not problem; sender not Idealista → `not_alert`
- [X] T009 [P] Add `tests/test_zones.py`: every fixture location text's municipality resolves (Brunete, Daganzo de Arriba, Villalbilla, Torrejón de Ardoz, Alcalá de Henares, Tres Cantos, Algete, Getafe, Paracuellos de Jarama, Mejorada del Campo); `"alto de San Isidro, San Isidro, Madrid"` → not recognised; an alias in a temp `zone_aliases.yaml` makes it resolve; text naming two municipalities → not recognised
- [X] T010 [P] Add `tests/test_derive.py` (core cases): one new-listing sighting creates listing `idealista:<code>` with price, area, bedrooms, zone, `first_seen`/`last_seen` = alert date, `published_at` = alert date, `price_updated_at` null, one `price_history` row; an attribute absent from the sighting stays null

### Implementation

- [X] T011 Extend `app/db.py`: add tables `import_runs`, `alert_emails`, `sightings`, `mailbox_state` and the new nullable columns on `listings` and `price_history` exactly as in [data-model.md](data-model.md); add a `migrate(conn)` called from `connect()` that runs `ALTER TABLE … ADD COLUMN` only for missing columns (check with `PRAGMA table_info`), so existing databases upgrade in place
- [X] T012 [P] Create `app/zones.py`: load `config/zones_madrid_region.csv` and `config/zone_aliases.yaml` (if present); `match_zone(location_text) -> (zone_id | None, municipality | None, district | None)` per research R10 (alias exact match first; else last comma segment, `slug()`-compared with municipalities; for Madrid the previous segment must slug-match one of the seeded districts); ensure the zone row exists via `db.ensure_zone`
- [X] T013 [P] Create `app/providers/idealista_alert.py` implementing [contracts/alert-reader.md](contracts/alert-reader.md) with the rules of research R9: `READER_VERSION = "idealista-2026.10"`; dataclasses `ReadResult`, `ListingBlock`, `Problem`; `read(msg: email.message.EmailMessage) -> ReadResult` using `html.parser.HTMLParser` (collect `<a href title>`, the `<mj-raw>` attribute line, the card price, the "ha bajado de … a …" sentence, the description text); subject regex `^¡(?P<kind>.+?) en tu búsqueda: (?P<search>.+)!$`; alert type from kind + `utm_campaign` (`express_newAd_sale_*`, `express_priceDrop_sale_*`); type map only for `Piso`, `Casa o chalet independiente`, `Chalet adosado`, `Chalet pareado`, `Promoción`; attribute tokens only `N hab.`, `N m²`, `Nª planta`, `exterior`, `con ascensor`, `Garaje incluido`, anything else → notice; prices parsed with `app.util.to_money`. No network, no inference
- [X] T014 Create `app/alerts.py` (pipeline core): `process_message(conn, raw: bytes, *, origin, file_name=None, mailbox_id=None, run_id) -> outcome` that parses with `email.message_from_bytes(policy=default)`, computes `email_id` (Message-ID or `sha256:`), returns `already` if `email_id` or `mailbox_id` exists, otherwise stores the `alert_emails` row with raw bytes; then, **without calling the reader**, records `failed` with reason "reenvío sin muestra" for a forward (subject starting `Fwd:`, `Fw:`, `RV:` or `Reenviado:`, case-insensitive, or any `message/rfc822` part; set `forwarded=1`) and `failed` with "formato sin muestra" for any email with a `text/plain` part (FR-017, research R9); otherwise calls the reader, maps the outcome per the contract table, writes the sighting for `imported`, and calls `derive.derive_listing` for the touched listing — all in one transaction per message. Also `start_run(conn, kind)` / `finish_run(conn, run_id, status, error=None)` maintaining the `import_runs` counters and notes (depends on T011, T013)
- [X] T015 Create `app/derive.py` with `derive_listing(conn, listing_id)`: load all sightings of the listing ordered by (`seen_at`, `email_id`) and compute the listing columns per [data-model.md § Extended: listings](data-model.md#extended-listings) and research R11 — for this phase: identity, latest non-null attributes, price of the latest sighting, `first_seen`/`last_seen`, `published_at`, zone via `zones.match_zone`, `source = 'idealista'`, `url = link_direct`, `title` = type text + location; insert or update the `listings` row; rebuild `price_history` rows with `origin` in (`alert`, `alert_previous`) for that listing (depends on T011, T012)

**Checkpoint**: T008–T010 pass; `process_message` on any fixture creates the expected listing in an
in-memory db.

---

## Phase 3: User Story 3 — Import saved alert files (P2) — first usable increment

**Goal**: the user imports `.eml`/`.mbox` files (CLI or UI) and sees the listings ranked, with a
summary that accounts for every email.

**Independent Test**: import `tests/fixtures/emails` into an empty db → 11 listings, summary
"12 emails: 11 importados, 0 ya procesados, 1 rechazado, 0 fallidos"; import again → 12 already
processed, 0 new.

### Tests first

- [x] T016 [P] [US3] Add `tests/test_alerts_import.py::test_import_fixture_folder` (with `no_network`): `import_paths(conn, [fixtures dir])` → run counts as above and sum = 12 (FR-002, SC-004); 11 listings with price, area-or-development, link (SC-002); second import → all `already`; a `.mbox` built in `tmp_path` from 3 fixtures imports 3; a `.msg` file is reported as "unsupported file format: save as .eml"; timing of the fixture import < 5 s (SC-001) in a separate test marked `@pytest.mark.slow`
- [ ] T017 [P] [US3] Add `tests/test_api_alerts.py::test_api_import` using `TestClient`: `POST /api/alerts/import` with two base64 fixtures → run summary per [contracts/api.md](contracts/api.md); malformed body → 400

### Implementation

- [x] T018 [US3] In `app/alerts.py` add `import_paths(conn, paths, kind="file_cli") -> run summary dict`: expand folders (non-recursive) to `*.eml`/`*.mbox`, read `.mbox` with `mailbox.mbox` (file name = `name#index`), process messages oldest `Date` first, record problems and notices, return the summary structure used by CLI and API
- [ ] T019 [US3] Add `import-emails PATH [PATH ...]` to `app/cli.py` printing the summary format of [contracts/cli.md](contracts/cli.md) (FALLO/RECHAZADO/AVISO lines, totals); exit code 0, or 1 if any email failed
- [ ] T020 [US3] Add `POST /api/alerts/import` and `GET /api/runs`, `GET /api/runs/{run_id}` to `app/main.py` per [contracts/api.md](contracts/api.md) (JSON body `{files:[{name, content_base64}]}`, no multipart)
- [ ] T021 [US3] In `app/static/index.html` Datos tab, add "Importar emails de alerta": a multi-file picker (`.eml,.mbox`) that base64-encodes files in the browser, calls `/api/alerts/import`, and shows the summary with its problem lines; in the listing detail show source "Idealista (email de alerta)", the email date(s) and the subject(s) it came from (US1-4)

**Checkpoint**: quickstart §2 passes. The tool is usable with saved alert files.

---

## Phase 4: User Story 2 — No duplicates; price changes and price drops tracked (P1)

**Goal**: repeated listings collapse to one; prices, history, published and updated dates are
correct whatever the order; price-drop alerts update the listing; the list sorts by published or
updated date; possible duplicates across sources are flagged and mergeable.

**Independent Test**: process the fixtures in every one of 20 random orders → identical listings
table and history; Torrejón (112842548) shows 645.000 €, history "670.000 before 2026-10-26" +
"645.000 on 2026-10-26", published unknown, updated 2026-10-26.

### Tests first (golden where scoring is touched, Article VII)

- [ ] T022 [P] [US2] Add `tests/test_derive_prices.py`: order independence (20 shuffles of the fixtures plus synthetic sightings, compare full listings + price_history dumps); later lower price updates price and history (US2-2); reverse chronological processing keeps the newest price (US2-3, FR-008); same-day different prices → higher price + flag `precios en conflicto el <fecha>`; price drop for a known listing (new-listing sighting at 670.000 on 23 Oct, drop 670→645 on 26 Oct) → one listing, price 645.000, `published_at` 23 Oct, `price_updated_at` 26 Oct (US2-4, FR-035); price drop for an unknown listing → created, `published_at` null, `alert_previous` row; stated previous price ≠ recorded → flag `la alerta dice precio anterior <X>, registrado <Y>`; older price drop than newest sighting → history only
- [ ] T023 [P] [US2] Add `tests/test_derive_user_values.py`: a listing entered by CSV with area 142 then an alert stating 150 → area stays 142, flag `la alerta dice 150 m² (<fecha>)` (FR-023); all flag strings exactly as in [data-model § Flag texts](data-model.md#flag-texts); price entered manually is never replaced by alert prices
- [ ] T024 [P] [US2] Add `tests/test_scoring_duplicates.py::test_duplicates_golden`: pairs at exactly 3.0 % area and 5.0 % price difference are flagged (inclusive), 3.01 %/5.01 % are not, unknown area or unrecognised zone or development → no flag; cite the hand calculation in a comment (|a−b|/max(a,b))
- [ ] T025 [P] [US2] Add `tests/test_api_sorting.py`: `GET /api/listings` returns `published_at`, `price_updated_at`; export CSV has both columns plus `found_via`, `scoring_version`

### Implementation

- [ ] T026 [US2] Complete `app/derive.py` price rules of research R11: tie → higher price + conflict flag; `alert_previous` rows for price drops ordered before the same-day `alert` row; previous-price mismatch flag; `price_updated_at`; respect `field_sources` (`manual`/`csv` never written; differing alert value → stored flag); never write null over a known value; store derivation flags in `listings.alert_flags` (defined in data-model; created by T011)
- [ ] T027 [US2] In `app/listings.py`, make `upsert_listing` record `field_sources` (`manual`/`csv`/`idealista_api` by source) for each non-null field it writes, so FR-023 can tell user values from alert values; keep its current behaviour otherwise
- [ ] T028 [US2] In `app/scoring.py`, read price history ordered by `day`, then `origin='alert_previous'` first, then `rowid`; add duplicate detection per research R15 producing flag "posible duplicado de <id>" on both listings; skip listings with `merged_into` set and show their links on the target
- [ ] T029 [US2] In `app/main.py`, add `POST /api/listings/{id}/merge` (sets `merged_into`) and include `published_at`, `price_updated_at`, `links`, `sightings` in `GET /api/listings`; add `published_at`, `price_updated_at` columns to `/api/export.csv`
- [ ] T030 [US2] In `app/static/index.html` Oportunidades table, add columns *Publicado* and *Actualizado* (dd/mm/aaaa or "desconocido"); clicking a header sorts by that column client-side, toggling direction, unknown dates always last; Score remains the default order (FR-036, research R19); in the detail, show price history with "antes del <fecha>" for `alert_previous` rows and a "Fusionar con…" action for duplicate flags

#### FR-019 "no longer available" and relisted (IDs appended to keep earlier IDs stable)

- [ ] T066 [P] [US2] Add `tests/test_availability.py`: `PATCH /api/listings/{id}` with `availability: "gone"` → listing still returned by `GET /api/listings` with flag `ya no disponible` and `availability_changed_at` set; `availability: "active"` undoes it; importing fixtures in which the listing is absent never changes `availability` (FR-019); a new sighting dated after the mark keeps `gone` and adds flag `vuelto a ver en una alerta el <fecha>` (spec edge case "Relisted"); invalid value → 400
- [ ] T067 [US2] In `app/main.py`, extend `PATCH /api/listings/{id}` to accept `availability: "active" | "gone"` (400 otherwise) and set `availability_changed_at` to today; in `app/scoring.py`, add the `ya no disponible` flag and sort `gone` listings after active ones without excluding them (depends on T066)
- [ ] T068 [US2] In `app/derive.py`, never write `availability`; add the relisted flag to `alert_flags` when a sighting's `seen_at` is later than `availability_changed_at` of a `gone` listing (data-model § Extended: listings)
- [ ] T069 [US2] In `app/static/index.html`, add "Marcar como ya no disponible" / "Deshacer" in the listing detail, grey out `gone` rows, and show the relisted flag

**Checkpoint**: quickstart §4 dates/sorting items pass; re-imports never duplicate.

---

## Phase 5: User Story 1 (part A) — Categories and "found via" (P1)

**Goal**: each alert gets a category from user rules; listings show "found via"; a new-build
category sets new-build only as a flag to confirm on cost estimates.

**Independent Test**: import the fixtures → Brunete/Daganzo "encontrado vía: new-build",
Getafe "house", Alcalá piso "flat", Algete (old "Viviendas" search) "unknown search"; change a rule
→ categories re-derived without re-importing.

- [ ] T031 [P] [US1] Add `tests/test_categories.py`: matching ignores case and accents; no match → `unknown`; two rules with different categories → `unknown` + flag listing both rules; a listing seen under two categories lists both (US1-9); editing rules via `PUT /api/categories` re-derives stored emails (FR-031); property type never changed by a category (FR-032)
- [ ] T032 [P] [US1] Add `tests/test_scoring_new_build.py::test_new_build_from_category_golden`: a `/inmueble/` listing (new-build not stated) whose sighting category is `new-build` → `new_build_origin='category'`, cost estimate uses IVA 10 % + AJD 0.75 % (hand calc for 400.000 €: 43.000 € taxes, cite `app/mortgage.py` rates and needs.example.yaml) and flag "obra nueva según la categoría de la alerta, confirma"; user sets second-hand → ITP 6 % (24.000 €) and no flag (US1-10, FR-033); a stated new-build (subject "Nueva obra nueva" or `/obra-nueva/`) → `new_build_origin='email'`, no flag
- [ ] T033 [US1] Create `app/categories.py`: load/save `config/alert_categories.yaml`; `categorise(subject_or_search_name) -> (category, matched_rules)` on `slug()` text; `recategorise_all(conn)` updating `alert_emails.category`, `category_rules_matched`, copying to sightings and calling `derive.derive_listing` for affected listings
- [ ] T034 [US1] Wire categories: `app/alerts.py` sets the category when storing an email; `app/derive.py` computes `categories` and `new_build`/`new_build_origin` per data-model; `app/scoring.py` adds flags "encontrado vía: …", "búsqueda desconocida", "reglas de categoría en conflicto: …", and the new-build-from-category flag next to the mortgage estimate
- [ ] T035 [US1] Add `GET/PUT /api/categories` to `app/main.py` and `categories` command to `app/cli.py` per contracts; `PATCH /api/listings/{id}` accepts `new_build: true|false|null` stored as user value (`new_build_origin='user'`)
- [ ] T036 [US1] In `app/static/index.html`: Datos tab section "Categorías de alerta" listing rules (editable rows) and each stored search name with its category and email count; listing detail shows "encontrado vía: …" and, on the mortgage block, the confirm/override control for the new-build flag

**Checkpoint**: categories work for imported files.

---

## Phase 6: User Story 5 — Unknown fields shown as unknown; scoring v2 (P2)

**Goal**: absent fields read "desconocido", hard filters on unknown fields flag instead of passing,
zones are never guessed, developments are kept out of affordability, scoring is versioned.

**Independent Test**: Villalbilla listing shows bathrooms, floor, elevator, terrace, garage, pool,
garden "desconocido"; with `require_garden: true` it is flagged "jardín desconocido", not excluded.

- [ ] T037 [P] [US5] Add `tests/test_scoring_unknown.py::test_unknown_fields_golden`: for each hard filter (`min_area_m2`, `min_bedrooms`, `require_garden`, `min_plot_m2`, `max_price`, `allow_zones`) a null field gives the flag listed in [data-model § Flag texts](data-model.md#flag-texts) (e.g. `jardín desconocido`) and no exclusion; existing behaviour for known values unchanged (re-run `tests/test_core.py`)
- [ ] T038 [P] [US5] Add `tests/test_scoring_zones.py::test_zone_less_median_golden`: listings with `zone_id` null are not grouped into a `None` median; hand-computed medians for a 6-listing example cited in the test
- [ ] T039 [P] [US5] Add `tests/test_scoring_development.py::test_development_golden`: development listing with stated price → price, affordability and momentum components `None`, flag "promoción: sin vivienda elegida", not excluded by `max_price`/`min_area_m2`/`min_bedrooms`, no duplicate check; after `PATCH` with unit price 450.000, area 120, bedrooms 4 (origin manual) it is scored like any listing (hand-checked affordability numbers cited)
- [ ] T040 [US5] In `app/scoring.py`: add `SCORING_VERSION = 2`; change `_hard_filters` to return flags for null fields instead of passing silently; skip null zones in `build_context` medians and flag "zona no reconocida: "<texto>"" (with `allow_zones` flagging, not excluding); development handling per research R13; add `scoring_version` to each listing dict returned by `rank()` (keeps the response a list, so the UI and `tests/test_core.py` need no change)
- [ ] T041 [US5] In `app/main.py`, `PATCH /api/listings/{id}` accepts unit values `price`, `area_m2`, `bedrooms` (recorded in `field_sources` as `manual`); add `scoring_version` to `/api/export.csv`
- [ ] T042 [US5] In `app/static/index.html`: show "desconocido" for null bathrooms, floor, elevator, terrace, garage, pool, garden, location; show the development label "precio de promoción, no de una vivienda" and the unit description, plus inputs to enter a chosen unit; show the "zona no reconocida" text with a hint to add it to `config/zone_aliases.yaml`

**Checkpoint**: `tests/test_scoring_*.py` pass; ranking reports scoring version 2.

---

## Phase 7: User Story 4 — Unreadable emails reported, never dropped (P2)

**Goal**: failed and rejected emails are listed with reasons, their content kept, and they can be
re-processed later without the file or the mailbox.

**Independent Test**: import the fixtures plus a non-Idealista email and a truncated alert →
summary lists them as rejected / failed with reasons; `reprocess-emails --failed` after a reader
version bump imports the fixed one.

- [ ] T043 [P] [US4] Add `tests/test_alerts_failures.py::test_failures_reported`: non-alert → rejected "no es un email de alerta reconocido" (US4-1); truncated fixture (card removed) → failed with what was expected and an excerpt (US4-2); neither creates or changes a listing (FR-009); the 2021 fixture → rejected "tipo de alerta no soportado"; re-process with a monkeypatched newer `READER_VERSION` that understands the case → imported, original raw unchanged (US4-3); a fixture re-wrapped as a forward (subject `Fwd: …`, and separately as a `message/rfc822` attachment) → failed "reenvío sin muestra", and a fixture with an added `text/plain` part → failed "formato sin muestra", neither creating a listing (FR-017)
- [ ] T044 [US4] In `app/alerts.py` add `reprocess(conn, scope="failed"|"all") -> run summary` that re-reads stored raw emails whose `reader_version` is older than the current one (or all), replacing their sightings and re-deriving touched listings
- [ ] T045 [US4] Add `reprocess-emails [--failed|--all]` to `app/cli.py`; add `GET /api/alerts/emails`, `GET /api/alerts/emails/{id}/raw`, `POST /api/alerts/reprocess` to `app/main.py` per contracts
- [ ] T046 [US4] In `app/static/index.html` Datos tab, add "Emails no importados": table of failed/rejected emails (date, subject, reason), a link to view raw, and a "Reprocesar" button

---

## Phase 8: User Story 6 — New since last sync or import (P3)

- [ ] T047 [P] [US6] Add `tests/test_alerts_new_since.py::test_new_since_last_run`: import batch A then batch B (fixture subsets) → `GET /api/listings?new_since_last_run=true` returns only listings first detected in B
- [ ] T048 [US6] Set `listings.first_run_id` in `app/derive.py` (the run of the earliest processed sighting; unchanged on re-derivation) and support `new_since_last_run=true` in `GET /api/listings` in `app/main.py`
- [ ] T049 [US6] In `app/static/index.html` Oportunidades, add a toggle "Solo nuevos desde la última sincronización/importación"

**Checkpoint — file path complete (target 2026-11-14)**: quickstart §1 (minus mailbox tests),
§2 and §4 pass. Usable on its own with saved alert files.

---

## Phase 9: User Story 1 (part B) — Mailbox sync (P1)

**Goal**: alerts arrive from the configured Gmail label with no step per email, every 15 minutes
and on demand, read-only, with visible status and loud failures.

**Independent Test**: with the fake mail source serving the fixtures, a sync imports them; a new
message added to the fake appears after the next scheduled tick; revoking (fake raises
`AuthRevoked`) pauses auto-sync and shows re-authorise steps.

### Tests first (all offline: `httpx.MockTransport` and a fake `MailSource`)

- [ ] T050 [P] [US1] Add `tests/test_mailbox_credentials.py`: with `CASA_APPDATA=tmp_path`, `save_refresh_token`/`load_refresh_token` round-trip; on Windows the stored bytes do not contain the token in clear (DPAPI); `repr()` of the secret holder never shows the value; app folder is never inside the repository root (assert raises if `CASA_APPDATA` points inside it)
- [ ] T051 [P] [US1] Add `tests/test_mailbox_oauth.py`: authorise URL contains only scope `https://www.googleapis.com/auth/gmail.readonly`, `code_challenge_method=S256`, `access_type=offline`, loopback `redirect_uri`; code exchange and refresh POST to `https://oauth2.googleapis.com/token` (MockTransport); `invalid_grant` → `AuthRevoked`; error messages contain method/path/status only, never tokens (scan `caplog` and exception text for the fake token strings)
- [ ] T052 [P] [US1] Add `tests/test_mailbox_gmail.py`: every request recorded by MockTransport is a GET to one of `users/me/profile`, `users/me/labels`, `users/me/messages`, `users/me/messages/<id>` (FR-016, mail-source contract); list calls carry `labelIds=<id>` and `q=after:yyyy/mm/dd`; pagination followed; `fetch_raw` base64url-decodes `raw`; a message lacking the label → `WrongFolder`; 429/5xx/timeout → `SourceUnavailable`; requests spaced ≥ 100 ms (patch the clock)
- [ ] T053 [P] [US1] Add `tests/test_sync.py` with a `FakeMailSource` serving fixture bytes: first sync uses `after = today − 30 days` and skips older messages (FR-027); second sync fetches nothing already stored (FR-026); new message → imported, summary counts only it (US1-2); same email also imported from file → already processed; interruption after N messages (fake raises mid-way) → those N stay processed, next sync resumes (SC-010); `AuthRevoked` → `auth_state=revoked`, `auto_sync=paused_auth`, scheduler skips (FR-029, US1-8); `FolderNotFound` → error "carpeta <nombre> no encontrada", nothing read; `SourceUnavailable` → error recorded, schedule continues; second concurrent sync → refused (FR-025); out-of-date true after a failure or 30 minutes without success (FR-028); 1,000-message fake backlog finishes < 10 min (SC-010) in a separate test marked `@pytest.mark.slow`

### Implementation

- [ ] T054 [P] [US1] Create `app/mailbox/__init__.py` with the `MailSource` protocol and the errors `AuthRevoked`, `FolderNotFound`, `SourceUnavailable`, `WrongFolder` per [contracts/mail-source.md](contracts/mail-source.md)
- [ ] T055 [P] [US1] Create `app/mailbox/credentials.py`: app folder from `CASA_APPDATA` or `%LOCALAPPDATA%\casa-radar` (refuse a path inside the repository); `load_client_secret()` reading `client_secret.json` (installed-app format); `save_refresh_token`/`load_refresh_token`/`delete_token` using DPAPI `CryptProtectData`/`CryptUnprotectData` via `ctypes` on Windows (`token.bin`), owner-only `token.json` elsewhere; a `Secret` holder with redacted `__repr__`/`__str__` (research R4)
- [ ] T056 [US1] Create `app/mailbox/oauth.py`: `authorize()` — PKCE S256 with `secrets`/`hashlib`, loopback `http.server` on `127.0.0.1:0`, open browser with `webbrowser`, wait ≤ 5 min, exchange code via `httpx` POST to the token endpoint, save refresh token; `access_token()` — refresh on demand, cache in memory until expiry, map `invalid_grant`/401 to `AuthRevoked`; scope constant `gmail.readonly` only (research R2, R3) (depends on T055)
- [ ] T057 [US1] Create `app/mailbox/gmail.py`: `GmailSource(MailSource)` over `httpx.Client(timeout=30)` with base `https://gmail.googleapis.com/gmail/v1/`; methods per contract; ≥ 100 ms between requests; no retries; errors mapped per contract table; `fetch_raw` verifies `labelIds` contains the folder id (request `format=raw` returns `labelIds`) (depends on T054, T056)
- [ ] T058 [US1] Create `app/alerts_sync.py`: `sync(conn, source, kind) -> run summary` per research R5 (window, overlap of 2 days, skip known `mailbox_id`, oldest first, one transaction per message via `alerts.process_message`, progress in `mailbox_state`, label re-resolution with "folder identity changed" notice); `SyncState` read/write helpers; module-level `threading.Lock` so a second call returns "sync already running"; `out_of_date(state, now)`; error mapping to `mailbox_state` per research R6 (depends on T014, T054)
- [ ] T059 [US1] In `app/main.py`: FastAPI lifespan starting an asyncio task that every 15 minutes runs `alerts_sync.sync` in a worker thread when `auth_state='valid'` and `auto_sync='on'`; endpoints `GET /api/mailbox`, `POST /api/mailbox/authorise`, `PUT /api/mailbox/folder`, `POST /api/mailbox/sync`, `POST /api/mailbox/disconnect` per [contracts/api.md](contracts/api.md); `GET /api/mailbox` never returns secrets and includes `reauthorise_steps` when revoked
- [ ] T060 [US1] Add `mailbox-setup [--label NAME]` and `sync [--wait]` to `app/cli.py` per [contracts/cli.md](contracts/cli.md) with exit codes 0/1/2/3
- [ ] T061 [US1] In `app/static/index.html`: status bar on every tab (cuenta, carpeta, última sincronización correcta, último error con hora, "Sincronizar ahora", progress during a sync); out-of-date warning above the ranking (FR-028); "sincronización detenida: permiso revocado o caducado" banner with the re-authorise steps (FR-029); Datos tab "Buzón" setup: where to put `client_secret.json` (shows the app folder path), "Autorizar" button, label input, the permission explanation text from the mail-source contract, "Desconectar"

**Checkpoint — v1 (2026-11-28)**: quickstart §3 and §5 pass on the real account.

---

## Phase 10: Polish & Cross-Cutting

- [ ] T062 [P] Update `README.md`: alert-email import, mailbox setup (Google Cloud project *In production*, Desktop client, label filter `from:noresponder@idealista.com`), where secrets live, how to revoke, `import-emails`/`sync`/`reprocess-emails`, `needs.example.yaml` → `needs.yaml`
- [ ] T063 [P] Add `tests/test_no_secrets.py`: scan the repository tree (excluding `.git`) for files named `client_secret*.json`, `token*.json`, `token.bin` and for strings shaped like Google refresh tokens (`1//0…`) — fail if any
- [ ] T064 Verify Article VIII end to end: run the ranking twice on the same db and needs → identical output; `scoring_version` present in API and CSV
- [ ] T065 Run [quickstart.md](quickstart.md) §1–§6 and record results (including SC-008: a new alert visible within 16 minutes while the app runs)

---

## Dependencies & Execution Order

### Phase dependencies

- **Phase 1 (Setup)**: T001–T002 done; T003–T007 independent; T004 starts with a user download.
- **Phase 2 (Foundational)**: after Phase 1; blocks all story phases. T011 → T014, T015; T012, T013
  parallel; T014 needs T013; T015 needs T012.
- **Phase 3 (US3)**: after Phase 2. First usable increment.
- **Phases 4–8 (US2, US1-A, US5, US4, US6)**: after Phase 3 (they are tested through file import).
  US2 first (derivation rules the others rely on); US1-A, US5, US4, US6 can then run in any order
  or in parallel, except that tasks editing the same file (`app/scoring.py`, `app/main.py`,
  `app/static/index.html`, `app/cli.py`, `app/derive.py`) must be serialised. Test files are one per task, so test tasks marked [P] are truly parallel.
- **Phase 9 (US1-B, mailbox)**: after Phase 3 (needs `process_message`); independent of 4–8, but
  planned after them per the delivery order.
- **Phase 10**: after the phases it checks.

### Within each phase

Tests first (fail), then data/model code, then services, then API/CLI, then UI.

## Parallel Examples

```text
# Phase 2, after T011:
T012 app/zones.py   |   T013 app/providers/idealista_alert.py   |   T008/T009/T010 tests

# Phase 4 tests together:
T022 tests/test_derive_prices.py   |   T023 tests/test_derive_user_values.py   |   T024 tests/test_scoring_duplicates.py   |   T025 tests/test_api_sorting.py   |   T066 tests/test_availability.py

# Phase 9, start together:
T050–T053 tests   |   T054 app/mailbox/__init__.py   |   T055 app/mailbox/credentials.py
```

## Implementation Strategy

1. **Phases 1–3** → import saved alert files; MVP of the delivery order (usable without a mailbox).
2. **Phases 4–8** → correct prices, dates, sorting, categories, unknowns, failures: the full file
   path, target **2026-11-14**. Stop and validate with quickstart §2 and §4.
3. **Phase 9** → mailbox sync, target **2026-11-28** (v1). If it slips, v1 ships with the file path
   and sync follows (plan, Article X).
4. **Phase 10** → docs, secret scan, quickstart run.

## Notes

- Commit after each task or logical group; never commit `data/`, `config/needs.yaml`, anything in
  `%LOCALAPPDATA%\casa-radar\`, or a non-anonymised email.
- Scoring changes (T024, T032, T037–T039) need the hand calculation written next to the test
  (Article VII).
- If a fixture reveals a token, attribute or type not covered by research R9, extend the reader and
  its test from that sample; never guess formats (Article VI).
