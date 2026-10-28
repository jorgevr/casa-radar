# Research: Import Candidate Homes from Portal Alert Emails

Phase 0 output for [plan.md](plan.md). Each item: Decision / Rationale / Alternatives considered.
Rewritten on 2026-10-28 for mailbox sync, categories, developments and price-drop alerts; the
file-only research of 2026-10-23 is superseded.

## R1. How the tool reads the mailbox

- **Decision**: the Gmail API (REST), authorised with OAuth 2.0 for installed apps and the single
  scope `https://www.googleapis.com/auth/gmail.readonly`. The household mailbox is Gmail (the
  samples' `Delivered-To`, ARC and `X-Google-Smtp-Source` headers show it).
- **Rationale**: `gmail.readonly` is the provider's own read-only permission, revocable by the user
  at <https://myaccount.google.com/permissions> (FR-030, Article III). With it the tool cannot
  modify, move, delete, mark as read or send, even by mistake (FR-016, SC-009). No mailbox password
  is ever seen. Gmail message ids are stable, so email identity does not depend on server numbering
  (FR-026).
- **Limit accepted (Clarification 2026-10-23)**: the scope covers the whole mailbox; Gmail offers no
  per-label scope. The one-label limit is enforced by the tool: every list call carries
  `labelIds=[<configured label id>]`, and each fetched message is checked to carry that label before
  it is stored; a message without it is discarded unread and reported as an internal error.
  The only call outside the label is one `labels.list` at setup, to resolve the label name the user
  typed to its id (FR-016 "what is needed to locate that folder").
- **Alternatives rejected**: IMAP with an app password (needs the account password, full access;
  Article III); IMAP with OAuth (`https://mail.google.com/` scope = full read/write/delete);
  Gmail `gmail.metadata` scope (no message bodies); forwarding alerts to a dedicated mailbox
  (rejected by the user, Clarification 2026-10-23).

## R2. OAuth client and its one-time setup

- **Decision**: the user creates, once, a Google Cloud project with an OAuth client of type
  "Desktop app", enables the Gmail API, and downloads `client_secret_<…>.json` into
  `%LOCALAPPDATA%\casa-radar\`. The tool runs the installed-app flow: it opens the system browser at
  Google's consent page with PKCE (RFC 7636) and a loopback redirect `http://127.0.0.1:<random
  port>/` (RFC 8252), exchanges the code at `https://oauth2.googleapis.com/token`, and keeps the
  refresh token.
- **Publishing status**: the OAuth consent screen MUST be set to **In production** (unverified,
  personal use). In **Testing** status Google expires refresh tokens after 7 days, which would stop
  sync every week. As an unverified app Google shows a "Google hasn't verified this app" screen once
  at consent; the user, who owns the project, continues past it. The setup guide states both facts.
  Verify at setup time; Google's rules can change.
- **Rationale**: nothing in the repository identifies the household's Google project; the client
  secret of an installed app is not confidential by Google's own definition, but it is still kept
  outside the repository (FR-030) and the repository ignores `client_secret*.json`/`token*.json`.
- **Alternatives**: a shared Casa Radar OAuth client published by the project (rejected: a
  verification process for a restricted scope, and one client for every user).

## R3. HTTP client and OAuth code: no new dependency

- **Decision**: implement the three OAuth calls (authorise URL, code exchange, refresh) and the four
  Gmail calls (`labels.list`, `messages.list`, `messages.get?format=raw`, `users.getProfile`) with
  `httpx`, already a dependency, plus the standard library (`http.server` for the loopback redirect,
  `secrets`/`hashlib` for PKCE, `webbrowser`). About 150 lines in one module behind a small
  interface ([contracts/mail-source.md](contracts/mail-source.md)).
- **Rationale**: Article X. The protocol surface is seven HTTP requests, all documented; the code is
  tested against `httpx.MockTransport` without touching Google (Article VI).
- **Alternatives rejected**: `google-api-python-client` + `google-auth-oauthlib` (adds about eight
  packages including `requests`, `oauthlib`, `httplib2`, `uritemplate`, for seven calls);
  `authlib` (one package, but a large general-purpose library for a fixed flow).

## R4. Where the authorisation lives and how it is guarded

- **Decision**: folder `%LOCALAPPDATA%\casa-radar\` (override with `CASA_APPDATA` for tests).
  Files: `client_secret.json` (copied by the user) and `token.bin`, the refresh token encrypted with
  Windows DPAPI for the current user (`CryptProtectData` through `ctypes`, standard library). On a
  non-Windows machine the token is stored as `token.json` with owner-only permissions and the setup
  screen says it is not encrypted.
- **Rationale**: the token reaches all personal mail (R1), so a copied file alone must not be usable
  on another account or machine. DPAPI needs no password prompt and no new dependency.
- **Never shown or logged**: secrets are held in one object whose `repr` is redacted; exceptions
  from the HTTP layer are re-raised with the URL and status only, never headers or bodies; a test
  greps captured logs and API responses for the token values.
- **Alternatives**: OS keyring via `keyring` (new dependency); plain JSON (rejected for the reason
  above).

## R5. Incremental sync and backfill

- **Decision**: each sync lists message ids in the label with Gmail search `after:<date>`:
  - first sync: `after:` = today − 30 days (FR-027);
  - later syncs: `after:` = date of the last successful sync − 2 days (overlap for clock skew and
    late delivery). If the app was closed for weeks, this still covers everything since the last
    success, so nothing is skipped.
  Ids already in `alert_emails.mailbox_id` are skipped without fetching (FR-026). New ids are fetched
  with `format=raw`, oldest first, and each one is stored and processed in its own transaction, so
  an interruption loses nothing (SC-010). `messages.list` returns at most 500 ids per page; pages are
  followed until exhausted.
- **Numbering reset** (spec edge case): Gmail ids do not get renumbered. The equivalent failure, the
  label being deleted and recreated with a new id, is detected at the start of each sync by
  re-resolving the label name; a changed id is reported as "folder identity changed" and the sync
  continues; already processed emails are recognised by `Message-ID` header (second identity key),
  so nothing is duplicated.
- **Alternatives**: Gmail `history.list` (fewer calls, but history ids expire after about a week
  offline and then a full list is needed anyway: two code paths for no benefit at this volume).

## R6. Schedule, concurrency and failure states

- **Decision**: an asyncio task started in the FastAPI lifespan runs a sync every 15 minutes while
  the server runs (FR-025); "sync now" (UI and CLI) calls the same function. A process-wide lock
  makes a second request return "sync already running" (FR-025). The blocking HTTP and parsing work
  runs in a worker thread so the UI stays responsive (SC-010).
- Failures map to the sync state ([data-model.md](data-model.md#new-mailbox_state-single-row)):
  - token refresh returns `invalid_grant` (revoked or expired) or 401 after refresh →
    `auth_state = revoked`, automatic sync **paused** until re-authorisation (FR-029);
  - network error, timeout, 5xx, 429 → error recorded, automatic sync keeps its schedule;
    for 429/5xx the sync stops at once (no retry loop inside a sync);
  - label not found → error "folder <name> not found"; no fallback (spec edge case).
- **Out-of-date warning**: shown when the last attempt failed or the last success is older than
  30 minutes (two intervals, FR-028).

## R7. Rate limits (Article IV)

- **Decision**: requests are sequential (no parallel fetches) with at least 100 ms between them,
  i.e. at most 10 requests/s, each `messages.get` costing 5 of the 250 quota units/user/second Gmail
  allows. A 1,000-email backlog then needs about 1,000 gets ≈ 2 minutes (SC-010). On 429 the sync
  stops and the next scheduled run continues.

## R8. Outbound endpoints (Article III plan check)

| Endpoint | When | Sent | Personal data from the tool |
|---|---|---|---|
| `accounts.google.com/o/oauth2/v2/auth` | setup and re-authorisation, opened in the **user's browser**, not by the tool | client id, scope, PKCE challenge, loopback URL | none |
| `oauth2.googleapis.com/token` | code exchange, token refresh | client id/secret, code + verifier or refresh token | none |
| `gmail.googleapis.com/gmail/v1/users/me/…` | sync | access token, label id, `after:` date, message ids | none |

No other host is contacted by this feature; file import contacts none (FR-014). Tests replace socket
creation with a function that raises, and assert zero connections (SC-006).

## R9. Idealista alert layout (from the 12 samples)

- **Recognition**: sender `noresponder@idealista.com`; subject
  `¡<kind> en tu búsqueda: <search name>!`. Alert type from `<kind>`, cross-checked with the
  `utm_campaign` parameter of the listing link:

  | Subject kind | `utm_campaign` | Alert type |
  |---|---|---|
  | `Nuevo <tipo>` / `Nueva obra nueva` | `express_newAd_sale_*` | `new_listing` |
  | `Bajada de precio` | `express_priceDrop_sale_*` | `price_drop` |
  | other, or the two disagree | other | `unsupported` |

  Other senders → `not_alert`. The 2021 sample (`noresponder.avisos@idealista.com`, older
  template) is `unsupported` and is the fixture for "unknown layout" (US4-2).
- **One listing per email**, read from the HTML part (the only part present):
  - listing code: the single distinct number in links `/inmueble/<code>/` (resale) or
    `/obra-nueva/<code>/` (development); zero or several distinct codes → failed;
  - title: the `title` attribute of the listing link (full text; the visible text is truncated with
    `...`), split at the first ` en ` into type text and location text;
  - price: the `NNN.NNN €` element of the card; price drops also state
    `ha bajado de <old>€ a <new>€`, and both must agree with the card price, else failed;
  - attributes: the `<mj-raw>` line under the price, tokenised against a closed list of the tokens
    seen in the samples: `N hab.`, `N m²`, `Nª planta`, `exterior`, `con ascensor`,
    `Garaje incluido`. Any other token (including plausible ones not yet seen, such as `interior` or
    `sin ascensor`) does not fail the email; it is listed in the summary as "unrecognised attribute:
    <token>" and the reader is extended when a sample shows it (Article VI);
  - development: link path `/obra-nueva/` and type text `Promoción` → `development = 1`; the unit
    description (e.g. "6 viviendas unifamiliares") is the card's description text, kept as stated;
  - new-build status: the email states it when the subject kind is `Nueva obra nueva` or the link is
    `/obra-nueva/`; a `/inmueble/` link states nothing (new-build stays unknown unless a category
    flag applies, FR-033).
- **Layouts without samples** (FR-017, Article VI): no sample is forwarded or has a `text/plain`
  part, so neither is parsed. Before calling the reader, the pipeline marks as `failed` (content
  kept, re-processable) any email whose subject starts with `Fwd:`, `Fw:`, `RV:` or `Reenviado:`
  (case-insensitive) or that contains a `message/rfc822` part ("forwarded alert without a sample"),
  and any email with a `text/plain` part ("layout without a sample"). Support is added from a real
  sample when one exists.
- **Links**: listing links point directly to `www.idealista.com` with tracking parameters; the
  direct link is the path without query, derived from the email itself (FR-015). The tool never
  requests any of them, nor images (FR-014).
- **Type mapping** (to the existing `norm_type`), only for type texts seen in the samples:
  `Piso`→`piso`, `Casa o chalet independiente`→`chalet`, `Chalet adosado`→`adosado`,
  `Chalet pareado`→`pareado`, `Promoción`→ type unknown (development). Any other type text → type
  `otro` and the flag "type not recognised: <text>" until a sample shows it.
- **Reader version**: `idealista-2026.10`; bumped whenever these rules change, so stored emails can
  be re-processed (US4-3).

## R10. Zone recognition (FR-013)

- **Decision**: the location text's last comma-separated segment is matched (after the existing
  `slug()`) against the 179 municipalities of the Comunidad de Madrid (INE "Relación de municipios y
  sus códigos por provincias", province 28, open data, stored once in
  `config/zones_madrid_region.csv` with source and download date). For `Madrid`, the segment before
  it must match one of the 21 districts already seeded; Idealista usually gives a barrio there
  ("San Isidro, Madrid"), which does not match, so the listing is "zone not recognised". The user
  can add entries to `config/zone_aliases.yaml` (location text → zone id) from the listing's flag;
  no automatic barrio table in v1.
- **Rationale**: every current sample outside Madrid city matches exactly (Brunete, Daganzo de
  Arriba, Villalbilla, Torrejón de Ardoz, Alcalá de Henares, Tres Cantos, Algete, Getafe,
  Paracuellos de Jarama, Mejorada del Campo). Idealista barrio names differ from the official ones,
  so an official barrio→district table would still guess.
- **Scoring impact**: zone medians skip listings without zone (today they would be grouped under a
  `None` zone); `allow_zones` flags "zone not recognised" instead of excluding.

## R11. Deriving listing values from sightings (FR-006–FR-008, FR-023, FR-035)

- **Decision**: alert-derived listing values are a pure function of the listing's sightings (sorted
  by alert date, then email id) plus the user's own values; after each email the touched listings
  are re-derived. This one rule gives the same result whatever the processing order (Article VIII)
  and makes re-processing, category changes and rule changes trivial.
  - current price = price of the latest-dated sighting; same date with different prices → the
    higher one, flag "conflicting prices on <date>";
  - `price_history` for alert listings is rebuilt from sightings: one row per date with a price
    change; a price drop also adds its stated previous price as a row marked `before` the alert date
    (FR-035);
  - stated previous price ≠ price of the latest earlier sighting → flag
    "alert says previous price <X>, recorded <Y>";
  - published date = date of the earliest `new_listing` sighting, else null; updated date = date of
    the latest sighting whose price differs from the one before it, else null (FR-036);
  - a field whose origin is `manual` or `csv` is never written; a differing alert value raises
    "alert says <value> (<date>)" (FR-023);
  - an alert never writes null over a known value (FR-011).
- **Alternatives**: incremental updates per sighting (rejected: order-dependent, hard to re-derive).

## R12. Categories (FR-031–FR-033)

- **Decision**: rules live in `config/alert_categories.yaml` (tracked: search names are not
  personal), editable from the Datos tab. Each rule: `contains: <text>` → `category: <name>`; match
  on `slug()` of the subject's search-name part. Starting rules from the samples:
  `obra nueva en tu zona personalizada → new-build`, `chalets en tu zona personalizada → house`,
  `apartamentos en tu zona personalizada → flat`. The old shared name `viviendas …` gets no rule
  (it covered two searches), so those sightings show "found via: unknown search".
- Category is stored on each sighting and recomputed for all stored emails when rules change.
- New-build from category: sets `new_build_flag = 'category'` only if no sighting states the status
  and the user has not set it; purchase-cost estimates then use new-build rates and show
  "new-build from alert category, confirm" (FR-033).

## R13. Developments (FR-034)

- **Decision**: `development = 1` listings keep their stated price in `price` (shown with the label
  "development price, not a unit price") but the scorer treats them as having no unit price until
  the user sets one: price, affordability and momentum components are `None` and flagged
  "development: no unit chosen", the `max_price`, `min_area_m2` and `min_bedrooms` filters flag
  instead of excluding, and the duplicate check skips them. When the user enters a unit price
  (field origin `manual`), the listing is scored normally.

## R14. Scoring version (Article VIII)

- **Decision**: `SCORING_VERSION = 2` (the current behaviour is implicitly 1). Changes: unknown-field
  flags on hard filters, zone-less medians, development handling, duplicate flags. Returned with
  every ranking and written in the CSV export. Golden tests per change (Article VII).

## R15. Possible duplicates (FR-018)

- Unchanged from the earlier plan: computed at ranking time, pairs in the same zone, type and
  bedrooms with `|a−b|/max(a,b) ≤ 0.03` for area and `≤ 0.05` for price, inclusive boundaries;
  unknown values or developments → no flag. Merge is a user action setting `merged_into`.

## R16. Raw storage and the repository (Articles III, IX)

- **Decision**: every email (sync or file) is stored with its full raw bytes, content hash, origin,
  outcome, reason and reader version in the local database (FR-010).
- **Prerequisite P0** (blocking finding): `data/casa.db` and `config/needs.yaml` are tracked by git.
  Before the first sync: untrack and ignore `data/`; move `needs.yaml` to an untracked file with a
  tracked `needs.example.yaml`; check whether earlier commits of `casa.db` or `needs.yaml` contain
  personal data before pushing (history rewrite is the user's decision).

## R17. Fixture privacy (FR-024)

- **Decision**: `tests/fixtures/anonymise_eml.py` (already written) produces the fixtures; its
  `--check` mode runs as a pytest test over `tests/fixtures/emails/`: header allowlist, placeholder
  recipient, greeting, redacted recipient/tracking/shape parameters, no foreign email address.

## R18. File import and upload without new dependencies

- **Decision**: CLI reads `.eml`/`.mbox` from paths; the UI sends selected files as JSON
  `{files:[{name, content_base64}]}` (multipart parsing would need `python-multipart`). Same
  pipeline as sync after the raw bytes are in hand.

## R19. Sorting by published / updated date (FR-036)

- **Decision**: the ranking API returns `published_at` and `price_updated_at`; the UI sorts on the
  client when a column header is clicked (score remains the default order); unknown dates sort last
  in both directions. The CSV export gains both columns.

## R20. Performance

- SC-001 (30 files < 5 s) and SC-010 (1,000 emails < 10 min) are dominated by HTML parsing and
  network: the standard-library parser handles a 50 KB email in a few ms; network at 10 req/s ≈
  2 min. A timing test covers SC-001 on the fixtures; SC-010 is checked with a fake mail source
  serving 1,000 copies of the fixtures with distinct ids.
