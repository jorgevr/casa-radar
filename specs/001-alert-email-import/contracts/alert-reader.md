# Contract: Alert reader

The only layout-specific code (`app/providers/idealista_alert.py`). Storage, derivation, ranking and
UI depend on this contract, not on the email layout. Reading rules: [research R9](../research.md#r9-idealista-alert-layout-from-the-12-samples).

## Input

One parsed email message (headers + MIME parts), already unwrapped by the generic layer: for a
forward, the reader receives the inner original and `forwarded = true`.

## Output

```text
ReadResult
  alert_type     : "new_listing" | "price_drop" | "unsupported" | "not_alert"
  search_name    : str | None                 # text after "en tu búsqueda:" in the subject
  listings       : list[ListingBlock]         # exactly 1 for the current layout; 0 when not read
  problems       : list[Problem]              # reasons the email (or a block) could not be read
  notices        : list[str]                  # non-failing: "unrecognised attribute: <token>"
  reader_version : str                        # "idealista-2026.10"

ListingBlock
  listing_code     : str                      # required
  price            : int | None
  previous_price   : int | None               # price_drop only; required there
  area_m2, bedrooms, floor : int | None
  exterior, elevator, garage : bool | None    # True only when stated; never False from absence
  type_text        : str | None
  property_type    : str | None               # mapped; None for developments
  development      : bool
  unit_description : str | None
  new_build_stated : bool | None              # True when stated; None otherwise
  location_text    : str | None
  link_tracking    : str
  link_direct      : str                      # derived from the link path, no request made
  raw_block        : str

Problem
  where    : str        # e.g. "listing link", "price drop sentence"
  expected : str        # e.g. "one distinct listing code"
  found    : str        # short excerpt of the raw evidence
```

## Rules

- MUST NOT make any network request, follow any link or fetch any image.
- MUST NOT infer a value: a field not literally present is `None`.
- MUST NOT raise on unexpected layouts; it returns `problems`.
- A price drop whose card price differs from the "a <new>€" price, or lacks the previous price, is a
  problem (not read).
- `reader_version` changes whenever these rules change.
- Every supported alert type has fixtures and a test asserting the exact `ReadResult`
  (FR-022): `new_listing` resale (houses, flat with attributes), `new_listing` development (2),
  `price_drop` (houses, flat), and the 2021 layout as `unsupported`.

## Caller outcome mapping

| ReadResult | Email outcome | Listing effect |
|---|---|---|
| `not_alert` | `rejected` — "not a recognised alert email" | none |
| `unsupported` | `rejected` — "unsupported alert type" (incl. older layouts, daily summaries) | none |
| `new_listing`/`price_drop`, 1 listing, no problems | `imported` | sighting stored; listing derived |
| `new_listing`/`price_drop`, problems | `failed` — reason from problems | none |

Notices go to the run summary and never change the outcome.
