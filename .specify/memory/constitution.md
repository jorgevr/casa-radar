<!--
Sync Impact Report — amendment 2026-10-23
- Version: 1.0.0 → 1.1.0 (MINOR: Article III materially expanded with one bounded exception; no
  existing protection removed)
- Modified: III Local-First & Private (title unchanged) — adds the mail-provider exception
  (read-only revocable permission, no password, only account identity + authorisation sent,
  configured folder only, no mailbox changes, content kept locally); "no personal data in outbound
  calls" stated explicitly; tokens added to secrets that must not be committed, logged or shown.
- Rationale: feature 001-alert-email-import reads Idealista alerts from the household's mailbox;
  alerts are the only discovery channel after API access was denied. Article IV already listed "the
  user's own mailbox" as a lawful source, but Article III forbade the necessary connection.
- Added / removed sections: none
- Templates: ✅ .specify/templates/plan-template.md (gate III mentions the mail-provider conditions)
             ✅ .specify/templates/spec-template.md, tasks-template.md (no change needed)
             ✅ .claude/skills/speckit-*/SKILL.md (no references to fix)
- Follow-up: re-run /speckit-plan for 001-alert-email-import (plan predates the amendment).
- Deferred: TODO(V1_DATE) still unset.

Previous report (1.0.0, 2026-10-22)
- Version: template → 1.0.0 (first ratified constitution)
- Principles: I Honest Data · II Estimates, Not Advice · III Local-First & Private · IV Lawful Sourcing ·
  V Human in the Loop · VI Fail Loudly · VII Test-First Money Maths · VIII Explainable & Reproducible ·
  IX Keep Raw Data · X Simplicity & Time-Box
- Added sections: Scope, Plan-Time Compliance, Governance
- Removed sections: none (template placeholders replaced)
- Templates: ✅ .specify/templates/plan-template.md (Constitution Check gates)
             ✅ .specify/templates/tasks-template.md (golden-value tests mandatory for money maths)
             ✅ .specify/templates/spec-template.md (no change needed)
             ✅ .claude/skills/speckit-*/SKILL.md (no agent-specific references to fix)
- Deferred: TODO(V1_DATE): the user has not set the v1 usability deadline.
-->

# Casa Radar Constitution

## Scope

Casa Radar is a single-user, local-first decision-support tool that helps one household choose a home
to buy in the Madrid region by ranking candidate homes against the household's needs and finances.
It informs a decision; it does not make one. This document sets rules, not technology choices.

## Core Principles

### I. Honest Data

- Missing data MUST NOT be scored as average, zero or any imputed value; the component is dropped and
  the remaining weights renormalised.
- Every score MUST show its coverage (how much of the weighted data backs it) and flags naming what it
  is *not* based on.
- Every displayed figure MUST carry its source and as-of date; unverified assumptions and placeholder
  values MUST be labelled as such (e.g. "assumption", "EJEMPLO", "not verified").

*Why*: a confident number built on gaps is worse than no number when the decision is a home.
*Plan check*: the plan lists each new figure with its source, date field and missing-data behaviour.

### II. Estimates, Not Advice

- Mortgage, tax and affordability outputs MUST be labelled as screening estimates, not offers or advice.
- Defaults (interest rate, term, taxes, costs, LTV, effort ceiling) MUST live in user-editable
  configuration and be visible where they are used; they MUST NOT be hard-coded in logic.

*Why*: bank offers and tax treatment vary; the user must see and own every assumption.
*Plan check*: no literal rate/tax/cost constant in the design; each output names the defaults it used.

### III. Local-First and Private

- Personal finance data (income, savings, equity from selling the current home, needs) MUST stay on the
  user's machine and MUST NOT appear in any outbound request, log shipped elsewhere, or telemetry.
- Outbound calls MUST go only to an explicit, reviewed allowlist of public sources, and MUST NOT carry
  personal data.
- Single exception, the user's own mail provider: the tool MAY connect to it to read the alerts the
  user configured, under all of these conditions:
  - access uses the provider's own read-only permission, granted and revocable by the user; the tool
    MUST NOT ask for or keep the mailbox password;
  - only the account identity and that authorisation are sent; nothing from the tool's own data
    (finances, needs, listings, scores) is ever sent;
  - reads are limited to the configured folder, and the tool MUST NOT change anything in the mailbox;
  - mail content retrieved is kept only on the user's machine.
- Secrets, credentials and authorisation tokens MUST NOT be committed, logged or displayed; they live
  outside the repository, which holds only examples and placeholders.

*Why*: the household's finances are the most sensitive data the tool touches; the mailbox exception
exists because alert emails are the only practical discovery channel, and it is bounded so that it
cannot become a path for the tool's own data to leave the machine.
*Plan check*: the plan lists every outbound endpoint (allowlisted or added with justification) and the
exact fields sent; none is personal. For the mail provider it states the permission requested, why
read-only is enough, the folder limit, and where the authorisation is stored (outside the repository).

### IV. Lawful Sourcing

- Only sources the user has the right to use: official APIs under their terms, open data, the user's
  own mailbox, and pages the user opens themselves.
- Bot-evasion, stealth or headless browsing to avoid detection, and automated crawling of listing
  portals are forbidden.
- Every connector MUST apply a polite rate limit and respect the source's published limits.

*Why*: the tool must be usable without legal risk or harm to the sources it depends on.
*Plan check*: each new source names its licence/terms, access method and rate limit.

### V. Human in the Loop

- Any content taken from a listing-portal page MUST originate from a page the user opened; the tool
  MUST NOT follow links, paginate or refresh portal pages on its own.

*Why*: keeps portal use within personal browsing and keeps the user in control of what is collected.
*Plan check*: the ingestion flow shows the user action that triggers each portal fetch.

### VI. Fail Loudly

- Connectors and parsers MUST stop on unexpected shapes and surface the raw evidence (payload, columns,
  field names) instead of guessing or silently skipping.
- Parsers MUST be written against real sample data stored in the repository (anonymised if needed).
- Automated tests MUST NOT touch live sites; they use fixtures, fakes or recorded samples.

*Why*: a silent mis-parse corrupts every ranking downstream and is hard to notice.
*Plan check*: the plan names the real sample each parser is built from and the failure output.

### VII. Test-First Money Maths

- Mortgage, tax, affordability and scoring logic MUST have golden-value tests, hand-checked against
  an independent calculation (e.g. an official simulator or a worked spreadsheet), written before or
  with the change; the check's source is recorded next to the test.

*Why*: arithmetic errors here directly mislead a large financial decision.
*Plan check*: tasks include the golden tests and cite where each expected value came from.

### VIII. Explainable and Reproducible

- Every score MUST decompose into named components with their values and weights.
- Weights and thresholds MUST live in configuration.
- The same inputs and configuration MUST produce the same output (no hidden randomness or clock use).
- Stored results MUST record the scoring version that produced them; changing scoring logic bumps it.

*Why*: the user must be able to ask "why is this home ranked here?" and get the same answer tomorrow.
*Plan check*: the plan shows the component breakdown and whether the scoring version changes.

### IX. Keep Raw Data

- Each ingested payload MUST be stored as received, with source and fetch time, so derived values can
  be recomputed after a parser or scoring change.

*Why*: sources change or disappear; re-fetching is not always possible or allowed.
*Plan check*: the data model shows where the raw payload is kept and how derivations are rebuilt.

### X. Simplicity and Time-Box

- Dependencies MUST be minimal; each new one needs a written reason and the simpler alternative rejected.
- Scope SHOULD favour what makes v1 usable; v1 MUST be usable for real decisions by
  TODO(V1_DATE).

*Why*: a tool that ships after the house is bought is worthless.
*Plan check*: new dependencies appear in the Complexity Tracking table; the plan states its v1 impact.

## Plan-Time Compliance

Every plan MUST contain a "Constitution Check" that marks each article I–X as pass, not applicable, or
violation. A violation MUST be justified in Complexity Tracking or the plan does not proceed.

## Governance

- This constitution overrides other practice docs where they conflict.
- Amendments MUST record a rationale (in the Sync Impact Report at the top of this file) and bump the
  version: MAJOR for removing or redefining an article, MINOR for adding or materially expanding one,
  PATCH for wording fixes.
- Dependent templates (plan, spec, tasks) MUST be re-checked on each amendment.

**Version**: 1.1.0 | **Ratified**: 2026-10-22 | **Last Amended**: 2026-10-23
