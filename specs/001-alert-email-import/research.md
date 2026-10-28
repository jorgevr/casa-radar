# Research: Import Candidate Homes from Portal Alert Emails

Phase 0 output for [plan.md](plan.md). Each item: Decision / Rationale / Alternatives considered.

## R1. Input format for "saved alert emails"

- **Decision**: accept `.eml` files (one message each) and `.mbox` files (many messages), from a
  folder (CLI) or a multi-file picker (UI). `.msg` (Outlook) is reported per file as
  "unsupported file format: save as .eml".
- **Rationale**: Gmail ("Download message"), Thunderbird and Apple Mail save `.eml`; Google Takeout
  exports `.mbox`. Both are read by the Python standard library (`email`, `mailbox`), so no new
  dependency (Article X). `.msg` needs a third-party reader.
- **Alternatives**: reading the mailbox directly over IMAP or the Gmail API (rejected: FR-016, and it
  would need credentials); `.msg` support via `extract-msg` (rejected for v1: new dependency, and
  Outlook can save as `.eml`).

## R2. Idealista alert layout (BLOCKED on samples)

- **Decision**: none yet. The reading rules for the alert body (how listing blocks, price, area,
  bedrooms, location text, listing code and links appear in HTML and text parts, and how a
  forwarded alert is wrapped) are written only from the anonymised samples in
  `tests/fixtures/emails/` (Article VI, FR-022). These rules live in one module
  (`app/providers/idealista_alert.py`) behind a fixed contract
  ([contracts/alert-reader.md](contracts/alert-reader.md)), so everything else can be built and
  tested before the samples arrive.
- **Open items to settle from the samples**: (a) the sender address(es) and subject patterns that
  identify a new-listing alert vs other Idealista email; (b) whether the listing code appears in
  visible text or only inside tracking links; (c) the structure of the location text (street,
  barrio, district, municipality); (d) whether HTML and text parts both carry the listings;
  (e) how Gmail/Outlook forwards wrap the original.
- **Gate**: tasks that implement `idealista_alert.py` MUST NOT start until at least one sample of each
  layout to be supported exists. Until then the reader rejects every email as
  "unsupported layout (no samples yet)", which is the fail-loud behaviour.

## R3. Listing identity and link derivation

- **Decision**: identity is `idealista:<listing code>` (source `idealista`, same as the existing API
  client), so alerts, any future API results and CSV rows that carry the code collapse onto one
  listing. If the code cannot be read from the email content without following a link, the block
  fails (spec edge case "tracking links"). The direct link `https://www.idealista.com/inmueble/<code>/`
  is built from the code; the tracking link is stored as found (FR-015).
- **Rationale**: FR-006; following a redirect would be an outbound request (FR-014, Articles III/V).
- **Alternatives**: identity by link (rejected: tracking links differ per email); source
  `idealista-alert` (rejected: would duplicate listings that also arrive by API or CSV with code).

## R4. Dates and price ordering

- **Decision**: a sighting is dated with the alert's `Date` header (the inner message's header when
  forwarded). `first_seen`/`last_seen` become the min/max sighting dates (not import day).
  The current price is the price of the latest-dated sighting; older ones only enter history
  (FR-007, FR-008). Price-history rows get the sighting date, and the ranking already reads history
  ordered by day.
- **Same-day conflict**: two sightings with the same date and different prices → the current price
  is the higher one (conservative for affordability, and independent of import order, so the result
  is reproducible), both go to history, and the listing is flagged "conflicting prices on <date>".
- **Alternatives**: import date (rejected: re-importing an old batch would look like new activity).

## R5. User-entered values win (FR-023) and blanks never erase (FR-011)

- **Decision**: track the origin of each listing field in a per-listing map (`field_sources`:
  field → `manual` | `csv` | `alert` | `idealista_api`). An alert sighting only writes a field whose
  current origin is empty or `alert`; if the origin is `manual`/`csv` and the values differ, the
  listing is flagged "alert says <value> (<date>)". An alert never writes a null.
- **Existing rows**: listings created before this feature get `field_sources` from their `source`
  column on first touch (`manual` → all non-null fields are `manual`).
- **Rationale**: the current `upsert_listing` overwrites every column, including with nulls; changing
  that for CSV is out of scope, so alerts get their own merge path.
- **Alternatives**: a full per-field history table (rejected: more than v1 needs; sightings already
  keep every alert value).

## R6. Zone recognition (FR-013)

- **Decision**: the known-zone list is the 179 municipalities of the Comunidad de Madrid plus the
  21 Madrid districts already seeded. The municipality list is a one-off download of the INE
  "Relación de municipios y sus códigos por provincias" (open data, province 28), stored in the
  repository with source and date. Location text matches when, after the existing `slug()`
  normalisation, it contains exactly one known municipality name (and for Madrid, exactly one district
  name). No match or more than one match → zone not recognised, original text kept, flag raised.
- **Scoring impact**: listings without zone must be skipped when computing zone medians (today the
  code would group all of them under one `None` zone and compare them with each other), and get no
  neighbourhood component; `allow_zones` flags them "zone not recognised" instead of excluding them.
- **Alternatives**: fuzzy matching (rejected: guesses, Article I); geocoding the text (rejected:
  outbound request with listing data, and no coordinates are needed for zone level).

## R7. Unknown fields and hard filters (FR-012)

- **Decision**: in the hard-filter step, a filter whose field is null adds the flag
  "<field> unknown" instead of silently passing (today `require_garden` with garden unknown passes
  with no flag). This applies to all listings, not just alerts. Scoring version bumps (R9).
- **Fields shown as "unknown"**: bathrooms, floor, elevator, terrace, garage, pool, garden, location.
  Floor, elevator, terrace, garage and pool are not stored today; they are added as nullable
  columns so the UI can show "unknown" consistently and future sources can fill them.

## R8. Possible duplicates (FR-018)

- **Decision**: computed at ranking time, not stored: for active, unmerged listings in the same zone,
  type and bedrooms, flag a pair when `|a−b| / max(a,b) ≤ 0.03` for area and `≤ 0.05` for current
  price. Boundaries are inclusive and covered by golden tests. Merging is a user action that sets
  `merged_into` on one listing; its sightings and price history are read together with the target's,
  and both links are shown.
- **Scale**: a few hundred listings; pairwise within a zone group is trivial.
- **Alternatives**: storing flags (rejected: stale when values change).

## R9. Scoring version (Article VIII)

- **Decision**: introduce `SCORING_VERSION` in the scoring module, starting at `2` (the current
  unversioned behaviour is implicitly `1`). It is returned with every ranking and written as a column
  in the CSV export. This feature changes scoring (R6, R7, R8), hence the bump.

## R10. Storage of raw emails (Article IX, FR-010) and privacy (Article III)

- **Decision**: each supplied message is stored with its full raw bytes, a content hash, sender,
  dates, outcome, reason, and the reader version, in the local database. Identity of an email is its
  `Message-ID` header when present, else the content hash; a second copy counts as "already imported".
- **Blocking finding**: `data/casa.db` (and `config/needs.yaml`, which will hold income and savings)
  are tracked by git today. Storing raw emails there would put the user's name, address and account
  links into the repository. **Prerequisite task**: untrack `data/` and ignore it; move personal
  values out of the tracked `needs.yaml` into an untracked local override (or ignore it and track a
  `needs.example.yaml`). Check whether past commits of `casa.db` contain personal data before pushing.

## R11. Privacy check on fixtures (FR-024)

- **Decision**: a test scans `tests/fixtures/emails/` and fails on: any email address other than
  `@example.com` placeholders and Idealista sender addresses; any URL whose query string carries a
  long opaque token (unsubscribe/tracking/login); any term listed in an untracked
  `config/private_terms.txt` (the user's name, street, phone). The test runs with the rest of the
  suite, so a failing check blocks committing a bad sample in normal workflow.
- **Alternatives**: a git pre-commit hook (could be added later; the test is enough for one user).

## R12. Upload path from the UI without new dependencies

- **Decision**: the UI reads the chosen files in the browser and sends one JSON request
  `{files:[{name, content_base64}]}` to the local server; the CLI reads a folder directly.
- **Rationale**: multipart form parsing in FastAPI needs `python-multipart`, a new dependency.
  30 emails are a few MB, well within one request.

## R13. Performance (SC-001)

- **Decision**: no special work. Parsing 30 messages with the standard library and a few hundred
  row writes in one transaction is well under a second; a timing test asserts < 5 s on the fixture
  set.

## R14. Proving zero network use (SC-006, FR-014)

- **Decision**: the import tests replace socket connection creation with a function that raises,
  so any outbound attempt fails the test. HTML is read with the standard-library parser, which never
  fetches images or styles.
