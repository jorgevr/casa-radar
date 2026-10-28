# Feature Specification: Import Candidate Homes from Portal Alert Emails

**Feature Branch**: `jorgevr/spec-kit` (spec directory `001-alert-email-import`)

**Created**: 2026-10-22 · **Amended**: 2026-10-23 (scope: read alerts directly from the mailbox;
then: provider read-only authorisation, alert categories, samples per saved search) · 2026-10-28
(developments, price-drop alerts, published/updated dates, layouts without samples, relisted)

**Status**: Draft

**Input**: User description: "Import candidate homes from portal alert emails. Idealista denied API
access, and automated scraping is ruled out by the constitution. The household receives saved-search
alert emails from the portals; these are the discovery channel, so their listings must reach the
ranked candidate list without manual retyping."

**Amendment 2026-10-23**: "The app must read the household's alert emails directly from the user's
mailbox with no manual step per email. Saving .eml files by hand was a misreading of the original
request, not a deliberate constraint." File import is kept as a secondary path for backfill,
offline use and building test fixtures.

## Context: current behaviour this feature builds on

- Candidate homes enter the tool today by CSV/manual import (and an unverified Idealista API client).
  Each listing is identified by its source plus the portal's listing code, or by its link when there
  is no code; importing the same identity again updates the listing instead of adding a new one.
- A listing records first-seen and last-seen dates, a status, and the original imported record.
  A price history entry is added when the listing is first seen and whenever its price changes.
- Zone is derived from municipality (and district for Madrid city). The ranked list scores listings
  0–100, drops missing components instead of averaging them, shows coverage and flags, and marks
  listings that fail the household's hard filters as *excluded* with reasons rather than hiding them.
- Current gap relevant here: re-importing a listing overwrites fields with blanks when the new record
  lacks them. Alert emails carry fewer fields than other sources, so this feature must not erase
  values known from elsewhere (FR-011).

## User Scenarios & Testing *(mandatory)*

### User Story 1 - New alerts reach the ranked list from the mailbox (Priority: P1)

The buyer configures the household's mailbox and the one folder that holds the Idealista alerts,
once, authorising the tool through the mail provider's own read-only permission (which the buyer
can revoke at any time). From then on, new alerts reach the ranked candidate list without the buyer doing anything per
email: the tool syncs on demand and automatically on a schedule while it runs. Every listing in those
alerts appears with price, built area, bedrooms, zone, a link to the listing and the date it was
detected, and is scored like any other candidate. The time of the last successful sync and the last
error are always visible.

**Why this priority**: alerts are the only practical discovery channel; a manual step per email
would mean missed or late candidates.

**Independent Test**: point the tool at a test mailbox folder holding the anonymised fixture alerts,
run a sync, and compare the ranked list against a hand-made list of the listings those emails
contain; then add one more alert to the folder and confirm it appears after the next scheduled sync
with no user action.

**Acceptance Scenarios**:

1. **Given** a configured mailbox folder with alerts containing N distinct listings and an empty
   candidate list, **When** the first sync runs, **Then** the ranked list shows N listings, each with
   price, area, bedrooms, zone, link and detection date as stated in the email, and the sync summary
   shows N new.
2. **Given** a completed sync, **When** a new alert arrives in the folder, **Then** its listings appear
   in the ranked list after the next scheduled sync without any user action, and the summary counts
   only the new email.
3. **Given** the user presses "sync now", **When** the sync completes, **Then** the last-successful-sync
   time updates and new listings appear.
4. **Given** an imported listing, **When** the user opens it in the ranked list, **Then** it shows its
   source ("Idealista alert email"), the email it came from, and the email's date.
5. **Given** an imported listing that fails a hard filter (e.g. fewer bedrooms than the minimum),
   **When** the ranked list is shown, **Then** it appears marked *excluded* with the reason.
6. **Given** a sync fails (e.g. mailbox unreachable), **When** the user looks at the ranked list,
   **Then** it shows the error, its time, and how old the last successful sync is.
7. **Given** any sync, **When** it runs, **Then** no email in the mailbox is modified, moved, deleted
   or marked as read, and no folder other than the configured one is read.
8. **Given** the user has revoked the tool's permission (or it has expired), **When** the next sync
   runs, **Then** sync stops, the main view says sync is stopped and shows the exact steps to
   re-authorise, and the ranked list carries the out-of-date warning until a sync succeeds.
9. **Given** a category rule "subject contains *obra nueva* → new-build" and an alert whose subject
   matches it, **When** its listings are shown, **Then** each shows "found via: new-build"; a listing
   also seen in a "flats" alert shows "found via: new-build, flats"; the property type stated in the
   email is unchanged.
10. **Given** a listing found via the new-build category whose email does not state new-build status,
    **When** its purchase costs are estimated, **Then** the estimate uses new-build costs and shows
    the flag "new-build from alert category, confirm" next to them; **When** the user sets the
    listing to second-hand, **Then** the estimate switches to second-hand costs and the flag
    disappears.

---

### User Story 2 - Re-syncs and re-imports never duplicate; price changes are tracked (Priority: P1)

Alerts are synced repeatedly and may also be imported from files (the same email twice, or several
alerts that repeat the same listing). Each listing appears once. When a later alert shows a different
price, the listing shows the new price and its price history keeps both.

**Why this priority**: alerts repeat listings constantly; duplicates would corrupt the ranking and the
"median of your own listings" price benchmark.

**Independent Test**: sync the fixture folder twice, import the same emails from files, then add a
fixture with a changed price; check listing count and price history.

**Acceptance Scenarios**:

1. **Given** a set of emails already processed, **When** a sync runs again or the user imports the same
   emails from files, **Then** the number of listings is unchanged and the summary reports every email
   as already processed.
2. **Given** a listing first seen at 300 000 €, **When** an email dated later shows it at 285 000 €,
   **Then** the listing shows 285 000 €, its history shows both prices with their email dates, and
   the existing price-drop signal reflects the change.
3. **Given** two emails showing different prices for the same listing, **When** they are processed in
   reverse chronological order, **Then** the current price is the one from the more recent email.
4. **Given** a listing first seen in a new-listing alert on 23 Oct at 670 000 €, **When** a price-drop
   alert dated 26 Oct says it dropped from 670 000 € to 645 000 €, **Then** the same listing (no new
   one) shows 645 000 €, its updated date is 26 Oct, its published date stays 23 Oct, and its history
   shows both prices.
5. **Given** listings with published and updated dates, **When** the user sorts the ranked list by
   published date or by updated date, **Then** the list is ordered by that date, with "unknown"
   dates last.

---

### User Story 3 - Import saved alert files (Priority: P2)

The buyer gives the tool a set of saved alert emails (`.eml` / `.mbox` files) for backfill beyond the
mailbox window, offline use, or to build test fixtures. They are processed with exactly the same
rules and summary as a sync.

**Why this priority**: secondary path; the mailbox sync covers day-to-day use.

**Independent Test**: import the anonymised fixture files into an empty tool and compare the ranked
list against the hand-made expected list.

**Acceptance Scenarios**:

1. **Given** an empty candidate list and a set of alert files containing N distinct listings,
   **When** the user imports them, **Then** the ranked list shows N listings and the import summary
   shows N new.
2. **Given** emails already processed by a sync, **When** the same emails are imported from files,
   **Then** they are reported as already processed and nothing is duplicated.

---

### User Story 4 - Unreadable emails are reported, never dropped (Priority: P2)

When an email cannot be understood (not an alert, unknown layout, a listing block missing its
identity), the tool reports which email and why, keeps the unparsed content, and imports nothing
guessed from it.

**Why this priority**: constitution VI (fail loudly); a silently skipped alert is a missed home.

**Independent Test**: process a batch mixing valid fixtures with a non-alert email and a truncated
one; check the report and that valid emails still import.

**Acceptance Scenarios**:

1. **Given** a batch with one email that is not a portal alert, **When** it is processed, **Then** the
   summary lists that email as rejected with the reason "not a recognised alert email" and the others
   import normally.
2. **Given** an alert whose layout differs from the known samples, **When** it is processed, **Then**
   it is reported as failed with what was expected and not found, its content is kept, and no listing
   is created or changed from it.
3. **Given** a failed email kept by the tool, **When** support for its layout is later added, **Then**
   the user can re-process it without the original file or the mailbox.

---

### User Story 5 - Missing fields show as "unknown" (Priority: P2)

Fields an alert email does not contain (bathrooms, floor, elevator, terrace, garage, pool, garden,
coordinates, and any other) are shown as "unknown", never inferred from title text, type or zone.

**Why this priority**: constitution I; a guessed garden or elevator would silently change the fit
score and hard filters.

**Independent Test**: process a fixture and inspect a listing whose email omits these fields.

**Acceptance Scenarios**:

1. **Given** an email that states price, area and bedrooms only, **When** the listing is shown,
   **Then** bathrooms, floor, elevator, terrace, garage, pool, garden and location read "unknown",
   and its flags say which score parts are missing as a result (e.g. nearby services not computed).
2. **Given** a hard filter on a field that is unknown (e.g. garden required), **When** the listing is
   ranked, **Then** it is flagged "garden unknown" rather than passed or excluded on a guess.

---

### User Story 6 - See what is new since the last sync or import (Priority: P3, optional)

After a sync or import the buyer can show only the listings that first appeared in it.

**Why this priority**: convenience; the summary already gives counts.

**Independent Test**: process batch A, then batch B; filter "new since last sync/import" shows only
listings first seen in B.

**Acceptance Scenarios**:

1. **Given** two consecutive syncs or imports, **When** the user selects "new since last sync/import",
   **Then** only listings first detected in the second one are shown.

---

### Edge Cases

- **Same listing in several alerts**: one listing; each sighting recorded with its email and date.
- **Same property under a different listing** (another alert, another agency, or a CSV/manual entry):
  both are kept and flagged "possible duplicate of …"; only the user merges them (Q1).
- **Relisted** (same listing code reappears after the user marked it "no longer available"): the
  listing stays "no longer available" (only the user changes it, FR-019), its history gains the new
  sighting, and it is flagged "seen again in an alert on <date>" so the user can undo the mark.
- **Price differs between two alerts**: the most recent email date wins; both go to history (US2-3).
  Two emails with the same date and different prices: the listing is flagged "conflicting prices".
- **Listing removed**: never inferred from a listing's absence from later alerts. In v1 only the user
  marks a listing "no longer available" (removal notices are out of scope, Q3); it stays visible.
- **Tracking-redirect links**: the tool never follows them (constitution III, V). It derives the
  listing identity and the direct listing link from the email content alone; if it cannot, the
  listing block is reported as failed with the link shown, rather than imported under a guessed
  identity.
- **Zone text matches no known zone**: the listing is imported under "zone not recognised" with the
  original text shown and flagged; it is not assigned to the nearest-sounding zone. Zone-dependent
  score parts are dropped (not averaged), and the listing still appears in the ranked list.
- **HTML-only, text-only, or both versions**: every current sample is HTML-only, and that layout is
  supported. Text-only alerts, and alerts carrying both versions, have no sample yet, so they are
  reported as failed ("layout without a sample") with their content kept, and supported once a real
  sample is added (constitution VI, FR-017). When both versions are supported they must agree; a
  disagreement on price, area or bedrooms is reported for that listing instead of picking one.
- **Forwarded alerts** (e.g. from another household member, in the folder or in a file): no sample
  exists, so a forwarded alert is reported as failed ("forwarded alert without a sample") with its
  content kept; it can be re-processed once a forwarded sample is added and supported. Once
  supported, the detection date is the original alert's date, not the forward's.
- **Email already processed** (same email in a file and in the mailbox, or a duplicate file):
  counted as already processed, not as a failure.
- **Alert contradicts a value the user entered** (e.g. user corrected area to 142 m², alert says
  150 m²): the user's value stays and the listing is flagged with the alert's value (FR-023).
- **Listing block with price or link but no area/bedrooms**: imported; missing values shown as
  unknown and flagged (US5).
- **Other Idealista emails** (removal notices, newsletters, daily summaries): reported as
  "unsupported alert type", content kept, no listing created or changed (Q3).
- **Price-drop alert for a listing not yet known** (e.g. published before the backfill window): the
  listing is created from the alert; its published date is "unknown"; the previous price goes to
  history as "before <email date>" and the new price at the email date (FR-035).
- **Price-drop alert whose previous price differs from the recorded current price** (an alert was
  missed): the new price is applied as usual, both stated prices go to history, and the listing is
  flagged "alert says previous price <X>, recorded <Y>".
- **Price-drop alert older than the newest sighting**: its prices go to history in date order, but
  the current price and updated date are not changed (FR-008).
- **Authorisation rejected, expired or revoked**: the sync stops; the main view shows "sync stopped:
  mailbox permission expired/revoked" with its time and the exact steps to re-authorise; automatic
  syncs pause until the user re-authorises, so repeated failed sign-ins cannot lock the account; the
  ranked list shows the out-of-date warning meanwhile. Authorisation secrets are never shown.
- **Mailbox unreachable** (offline, server down, timeout): the sync stops with the error and time;
  automatic syncs keep retrying on schedule; the ranked list shows how old the last successful sync is.
- **Configured folder missing or renamed**: the sync stops with "folder <name> not found"; the tool
  MUST NOT fall back to any other folder.
- **Non-alert and unsupported emails in the folder**: each is reported once as rejected in the
  summary of the sync that found it, stored, and never reprocessed or re-reported by later syncs.
- **Alert subject matches no category rule**: the sighting's category is "unknown" and the listing
  shows "found via: unknown search"; nothing else changes.
- **Alert subject matches rules of two different categories**: the category is "unknown" and the
  listing is flagged with the rules that matched, rather than picking one.
- **Same listing under several categories** (e.g. a new-build flat in both the new-build and flats
  searches): the listing keeps every category it was seen under.
- **New-build category vs what the email states**: if the email states new-build or second-hand, the
  email wins and no category flag is raised; if the email says second-hand but the category is
  new-build, the listing is flagged "alert category says new-build, email says second-hand".
- **User changes the category rules**: categories are re-derived from the stored subjects of all
  emails, so every listing reflects the current rules.
- **New-build alert shows a development** (one price, several unit types, no area or bedrooms) rather
  than one home: one candidate listing marked "development", kept out of affordability, price filters
  and duplicate checks until the user enters a specific unit's values (FR-034).
- **Daily-summary alerts** (several listings in one email): the household uses immediate alerts only,
  so no sample exists; such an email is reported as "unsupported alert type" (FR-020, FR-022).
- **Message numbering reset by the server**: the tool notices that its record of processed messages
  no longer matches the folder, re-checks the folder within the backfill window, skips every email
  already processed (by the email's own identity, not its position), and reports "mailbox numbering
  reset detected" in the summary. Nothing is duplicated or skipped.
- **Very large first-sync backlog**: processed oldest first in portions; progress is visible; the app
  stays usable; an interrupted sync resumes where it stopped without reprocessing; the summary
  covers the whole backlog once finished.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: Users MUST be able to give the tool a set of saved alert emails in one action (e.g. a
  folder of saved messages) and receive an import summary (US3).
- **FR-002**: Every sync and every file import MUST produce a summary that accounts for every email
  it found, each as imported, already processed, rejected (not an alert) or failed, with the reason;
  the four counts MUST sum to the total.
- **FR-003**: For each listing in an imported email the tool MUST capture, when the email states them:
  price, built area, bedrooms, property type, location text, listing link and listing code, plus any
  other attribute the email states (e.g. floor, exterior, elevator, garage included). An attribute the
  email does not mention stays unknown; it MUST NOT be read as "no" (FR-011).
- **FR-004**: Each imported listing MUST show its detection date (the alert email's date), its source
  ("Idealista alert email") and which email(s) it came from.
- **FR-005**: Imported listings MUST appear in the existing ranked list and be scored, filtered and
  flagged by the same rules as every other listing.
- **FR-006**: Processing an email or listing already known MUST NOT create a second listing; identity
  MUST be the portal's listing code when present.
- **FR-007**: When a later-dated email shows a different price, the tool MUST update the current
  price and add an entry to the listing's price history dated with the email's date, unless the
  current price was entered by the user (FR-023).
- **FR-008**: Prices from an email older than the newest one already seen for that listing MUST be
  added to history in date order but MUST NOT replace the current price.
- **FR-009**: Emails or listing blocks the tool cannot understand MUST be reported with the email,
  the reason and what was expected; they MUST NOT create or change any listing.
- **FR-010**: The tool MUST keep the content of every email it processes (synced or imported,
  imported or failed), so listings can be re-derived and failed emails re-processed later without
  the original file or the mailbox. Stored content MUST be kept in full (including the user's name,
  address and account links) and only on the user's machine.
- **FR-011**: A field absent from an email MUST be shown as "unknown" and MUST NOT be inferred; an
  email that lacks a field MUST NOT erase a value already known for that listing from another source.
- **FR-012**: Hard filters on an unknown field MUST flag the listing ("<field> unknown"), neither
  passing nor excluding it.
- **FR-013**: Location text that matches no known zone MUST be shown as "zone not recognised" with
  the original text, and MUST NOT be mapped to a guessed zone.
- **FR-014**: The only network connection the tool MAY make for this feature is to the configured
  mailbox server, during a sync. It MUST NOT open listing pages, follow tracking links, or download
  images or other content referenced by an email. File import MUST make no network connection.
- **FR-015**: Tracking links MUST be stored as found; a direct listing link MUST be shown only when
  it is derivable from the email content itself.
- **FR-016**: The tool MAY connect to ONE configured mailbox, read-only, limited to ONE configured
  folder/label that holds only portal alerts. It MUST NOT read any other folder, and MUST NOT modify,
  move, delete, mark as read, send, reply to, or unsubscribe from any email. The configured mailbox
  is the household's personal mailbox, and the configured folder/label is one inside it. Because the
  provider's read-only permission may cover the whole mailbox, the tool MUST NOT list, open or fetch
  any message, folder name or metadata outside the configured folder beyond what is needed to locate
  that folder, and the setup screen MUST tell the user what the permission technically allows.
- **FR-017**: The tool MUST accept the alert layouts covered by real samples (currently HTML-only,
  not forwarded). Text-only, two-version and forwarded alerts MUST be reported as failed with the
  reason "layout without a sample" and kept for re-processing (FR-010) until a real anonymised
  sample is added and supported (FR-022). Once two-version alerts are supported, a disagreement
  between the versions on price, area or bedrooms MUST be reported for that listing.
- **FR-018**: Two listings with different listing codes or sources MUST be flagged "possible
  duplicate of …" (each naming the other) when they share zone, property type and bedrooms, their
  areas differ by at most 3% and their current prices by at most 5%. If any of these values is
  unknown or the zone is not recognised, no flag is raised. Flagged listings MUST NOT be merged
  automatically; the user MUST be able to merge them, keeping both links and the combined price
  history.
- **FR-019**: A listing MUST become "no longer available" only when the user marks it (or, in a later
  version, an email explicitly says so); absence from later alerts MUST NOT change its status. Such
  listings MUST NOT be deleted and MUST remain visible with their history, and the user MUST be able
  to undo the mark.
- **FR-020**: In v1 the tool MUST recognise Idealista new-listing alerts and price-drop alerts, and
  report any other Idealista email (removal notice, newsletter, daily summary) as "unsupported alert
  type".
- **FR-021**: The tool SHOULD let the user show only listings first detected in the most recent
  sync or import (US6).
- **FR-022**: Email-reading rules MUST be built from the real anonymised samples in the fixtures, and
  every supported layout MUST have at least one sample. Before planning, the fixtures MUST include at
  least one real anonymised alert for EACH of the household's saved searches (new-build, flats,
  homes).
- **FR-023**: When an alert states a value (price included) that differs from one the user entered
  manually or by CSV for the same listing, the tool MUST keep the user's value and flag the listing
  "alert says <value> (<email date>)"; the alert's value MUST be kept with that sighting. Values
  that came from earlier alerts follow FR-007/FR-008 instead.
- **FR-024**: Sample emails added to the repository MUST NOT contain the recipient's name, email
  address, postal address, or links tied to the user's portal account (unsubscribe, tracking, login);
  a check MUST confirm this before samples are committed.
- **FR-025**: The tool MUST sync the configured folder when the user asks ("sync now") and
  automatically every 15 minutes (fixed) while the app is running.
  Two syncs MUST NOT run at the same time.
- **FR-026**: Sync MUST be incremental: an email processed once (with any outcome) MUST NOT be
  processed again by later syncs. Only an explicit user re-process (US4-3) re-reads stored emails.
  Email identity MUST NOT depend on the server's message numbering.
- **FR-027**: The first sync MUST process the emails in the folder from the last 30 days (by alert
  date) and none older; older emails can be added deliberately by file import.
- **FR-028**: The time of the last successful sync and the last error (time and reason) MUST always
  be visible in the main view. When the last attempt failed, or the last successful sync is older than
  two scheduled intervals, the ranked list MUST show a warning that it may be out of date.
- **FR-029**: A sync that cannot complete (authorisation rejected, expired or revoked; mailbox
  unreachable; folder missing) MUST stop and report the error; emails stored before the failure stay
  processed, and no email is marked processed unless it was stored. When authorisation is rejected,
  expired or revoked, the main view MUST say that sync is stopped and show the exact steps to
  re-authorise, and automatic syncs MUST pause until the user re-authorises.
- **FR-030**: The user MUST authorise the tool through the mail provider's own read-only permission,
  revocable by the user at any time from the provider's side; the tool MUST NOT ask for or keep the
  mailbox password. Authorisation secrets MUST NOT be stored in the repository, written to any log or
  error message, sent anywhere other than the mail provider, or shown after authorisation. They MUST
  be kept in a per-user application folder outside the repository (e.g. `%LOCALAPPDATA%\casa-radar\`),
  which the tool can update as the authorisation is renewed. As a second safety net, the repository
  MUST ignore authorisation files by name (client secret and token files) even though none should
  ever be inside it.
- **FR-031**: The user MUST be able to configure explicit category rules, each "subject contains
  <text> → <category>" (e.g. new-build, flat, house); matching ignores case and accents. Each alert
  gets the category of the rule its subject matches; no match, or matches with different
  categories, gives "unknown". Changing the rules MUST re-derive the categories of all stored emails.
- **FR-032**: The category MUST be stored on each sighting and shown on the listing as "found via:
  <category>, …", listing every category the listing was seen under. A category MUST NOT set or
  overwrite the listing's property type.
- **FR-033**: A new-build category MAY set the listing's new-build status only when no email states
  that status, and only as the visible flag "new-build from alert category, confirm", shown wherever
  purchase costs are estimated. The user MUST be able to confirm or override it; a user value is
  kept over any later alert (FR-023). A status stated in an email takes precedence over the category.
- **FR-034**: An alert that presents a development (one promotion of several homes, with one stated
  price and a description of the units) MUST become ONE candidate listing marked "development",
  identified by the development's listing code. Its stated price MUST be shown as stated and labelled
  "development price, not a unit price"; the unit description is shown as stated. Until the user
  enters the values of a specific unit (price, area, bedrooms; FR-023), the listing MUST be left out
  of affordability, price-based score parts, price hard filters and duplicate checks (FR-018), with
  those parts flagged "development: no unit chosen" rather than computed from the stated price.
- **FR-035**: A price-drop alert MUST update the existing listing with the same listing code, never
  create a second one: it sets the current price and the updated date (FR-036) and adds the price to
  history, following FR-007, FR-008 and FR-023 like any other sighting. The previous price it states
  MUST be kept with the sighting; if it differs from the recorded current price, the listing MUST be
  flagged with both values. If the listing is not yet known, it MUST be created from the alert.
- **FR-036**: Each listing MUST show a published date and an updated date, and the user MUST be able
  to sort the ranked list by either. The published date is the date of the earliest new-listing alert
  for that listing, and "unknown" when the listing has only been seen in other alert types or entered
  by the user. The updated date is the date of the most recent alert that changed its price, and
  "unknown" when the price has never changed. Unknown dates sort last.

### Key Entities

- **Alert email**: one processed message; where it came from (mailbox sync or file), sender portal,
  subject, alert date, alert type, category, original content, processing outcome and reason, and
  whether it is a forward (reported as failed until forwards are supported, FR-017).
- **Listing sighting**: one appearance of a listing in one alert email; the values stated there
  (price, area, bedrooms, type, location text, link), the email date and the alert's category. Many
  sightings per listing.
- **Category rule**: user-configured "subject contains <text> → <category>"; categories name the
  household's saved searches (new-build, flat, house).
- **Candidate listing** (existing): the deduplicated home being ranked; current values, first/last
  detection dates, published date, updated date, status, price history, flags.
- **Import run**: one sync or one file import; when it ran, how it was started (schedule, "sync now",
  file import), its summary counts, and which listings it first detected (for US6).
- **Mailbox sync state**: the one configured mailbox (account shown without secrets) and folder;
  authorisation status (valid, expired, revoked) and the steps to re-authorise;
  backfill start date; record of which emails in the folder have been processed; time and outcome of
  the last attempt; time of the last successful sync; last error; whether automatic sync is paused
  and why; progress of a sync in progress.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A folder of 30 alert emails imports, summary included, in under 5 seconds on the user's
  machine.
- **SC-002**: On the fixture set, at least 95% of imported listings have price, area and link; the
  rest are flagged with what is missing.
- **SC-003**: Processing the fixture set twice (by sync, by file, or one of each) yields exactly the
  same number of listings as once (zero duplicates), and every listing's price history matches a
  hand-built expected history.
- **SC-004**: 100% of emails found by a sync or supplied as files appear in that summary under
  exactly one outcome; zero are silently skipped.
- **SC-005**: Zero listing fields are shown with a value the source email did not state (checked
  against the fixtures).
- **SC-006**: During a sync, zero network connections are made to any destination other than the
  configured mailbox server; during a file import, zero network connections are made.
- **SC-007**: After the one-time mailbox setup, the buyer takes zero actions per email for new alerts
  to appear in the ranked list.
- **SC-008**: A new alert placed in the configured folder appears in the ranked list within 16 minutes
  (one 15-minute interval plus 1 minute) while the app runs.
- **SC-009**: After any failed sync, the error, its time and the age of the last successful sync are
  visible in the main view in 100% of cases; zero emails in the mailbox change state (read flag,
  folder, existence) as a result of any sync.
- **SC-010**: A first-sync backlog of 1,000 emails completes in under 10 minutes without making the app
  unusable, and an interruption at any point loses no work already done.

## Assumptions

- Only Idealista alert emails are in scope; other portals come in later specs.
- The household sets up, in their mail provider, a rule that puts Idealista alerts into one folder or
  label; the tool reads that folder only. Emails that land there by mistake are rejected, not read
  beyond identifying them as non-alerts.
- File import (`.eml` / `.mbox`) remains for backfill beyond the window, offline use and building
  test fixtures.
- Real anonymised sample emails are in `tests/fixtures/emails/` (12, received 2021-03 to 2026-10):
  new-build (2, both developments), houses (7) and flats (2 current, 1 from 2021); 3 of them (2
  houses, 1 flat) are price-drop alerts (FR-022). All current ones are HTML-only with one listing per
  email. The 2021 flat alert uses an older layout; it is not a supported layout and serves as the "unknown layout" case
  (US4-2). Layouts not covered by a sample are reported as failed. Tests never connect to a real
  mailbox (constitution VI).
- All saved searches send immediate alerts (one listing per email); none uses the daily summary.
- Alert subjects name the saved search ("…en tu búsqueda: <search name>!"), so category rules are
  written against the search name. The current searches are named "Obra nueva en tu zona
  personalizada", "chalets en tu zona personalizada" and "apartamentos en tu zona personalizada".
  Older alerts under "Viviendas en tu zona personalizada" came from more than one search (houses and
  flats), so a rule for that name cannot tell them apart.
- Detection date is the alert email's date; the processing date is recorded too.
- Email content may include the user's name, address and account links; it is kept in full on the
  machine only (constitution III, IX) and anonymised before being committed as fixtures (FR-024).
- Alert emails carry only summary data, so amenity distances and other location-based parts will
  usually be unavailable; this is expected and shown via coverage and flags, not filled in.
- **Constitution dependency**: reading the household's own mailbox is allowed by the Article III
  mail-provider exception added in constitution v1.1.0 (2026-10-23): read-only revocable permission,
  only account identity and authorisation sent, configured folder only, no mailbox changes, content
  kept locally.
- Automatic syncing happens only while the app is running; nothing runs in the background after it
  is closed.

## Clarifications

### Session 2026-10-23

- Q1: Same property under a different listing: merge automatically or flag? → A: flag "possible
  duplicate of …"; only the user merges (FR-018).
- Q2: When is a listing "no longer available"? → A: only when an email explicitly says so or the
  user marks it; never from absence (FR-019). With Q3 (no removal notices in v1), this means
  the user marks it.
- Q3: Which Idealista alert types are in scope for v1? → A: new-listing alerts only (FR-020).
  Superseded on 2026-10-28: price-drop alerts are also in scope (FR-035).
- Q: When are two listings flagged "possible duplicate"? → A: same zone, property type and bedrooms,
  area within ±3% and price within ±5% (FR-018).
- Q: An alert states a value that differs from one the user entered (manually or by CSV)? → A: keep
  the user's value and flag the listing with the alert's value (FR-023).
- Q: Should stored emails keep the user's name, address and account links? → A: keep in full on
  the machine only; samples committed to the repository must have them removed, checked before
  committing (FR-010, FR-024).
- Scope amendment (user, 2026-10-23): alerts are read directly from one configured mailbox folder,
  read-only, with no manual step per email; file import becomes secondary (US1, US3, FR-014, FR-016,
  FR-025–FR-030, SC-006–SC-010).
- Amendment (user, 2026-10-23): authorisation through the provider's own revocable read-only
  permission, with visible stop and re-authorise steps (FR-029, FR-030); alert categories from
  user-configured subject rules, shown as "found via" and never overwriting property type (FR-031,
  FR-032); new-build category only as a flag to confirm on cost estimates (FR-033); samples for each
  saved search before planning (FR-022); development-vs-listing left open (FR-034); rejected emails
  in the folder reported once, never reprocessed.
- Q: Which mailbox does the tool get permission to read? → A: a folder/label inside the household's
  personal mailbox, not a dedicated account (FR-016). Accepted risk: the permission may reach all
  personal mail, so the one-folder limit is enforced by the tool and the authorisation must be guarded.
- Q: Where are the authorisation secrets kept? → A: a per-user folder outside the repository, such as
  `%LOCALAPPDATA%\casa-radar\`; client secret and token files are also ignored by the repository as a
  second safety net (FR-030).
- Q: How often does the automatic sync run? → A: fixed every 15 minutes while the app runs (FR-025,
  SC-008); the out-of-date warning (FR-028) therefore appears after 30 minutes without a success.
- Q: How far back does the first sync go? → A: 30 days (FR-027); older alerts only by file import,
  because removal is manual and a long backfill would fill the ranking with sold homes.

### Session 2026-10-28

- Q: Is a new-build development one candidate listing or a separate entity grouping its units? →
  A: one candidate listing marked "development", kept out of affordability, price filters and
  duplicate checks until the user enters a specific unit (FR-034). The samples confirmed that
  new-build alerts are developments (one price, unit types listed, no area or bedrooms).
- Q: Do any saved searches use the daily summary? → A: no; immediate alerts only, so daily-summary
  emails are reported as unsupported.
- Samples (user, 2026-10-28): current alerts for every saved search added, including the renamed
  "chalets" and "apartamentos" searches and three price-drop alerts; anonymised copies with the
  check script are in `tests/fixtures/` (FR-022, FR-024).
- Q: Are price-drop alerts in scope for v1? → A: yes. A price-drop alert updates the existing
  listing (same listing code): current price, price history and an updated date (FR-020, FR-035).
  Each listing also gets a published date (from its new-listing alert), and the ranked list can be
  sorted by published or updated date (FR-036).
- Analysis remediation (2026-10-28): text-only, two-version and forwarded alerts are reported as
  failed until a real sample exists (FR-017, constitution VI); a relisted listing the user marked
  "no longer available" stays so and is flagged "seen again in an alert on <date>" (FR-019).
