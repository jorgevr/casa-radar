# Contract: Alert reader

The only layout-specific code. Everything else (storage, merge, ranking, UI) depends on this
contract, not on the email layout, so it can be built and tested before the samples exist.

## Input

One parsed email message (headers + MIME parts), already unwrapped by the generic layer:
if the message is a forward, the reader receives the inner original and `forwarded = true`.

## Output

```text
ReadResult
  alert_type   : "new_listings" | "other_idealista" | "not_idealista"
  listings     : list[ListingBlock]           # empty unless alert_type = new_listings
  problems     : list[Problem]                # blocks or parts that could not be read
  reader_version : str

ListingBlock
  listing_code   : str                        # required; block is a Problem if absent
  price, area_m2, bedrooms : number | None    # None when the email does not state it
  property_type  : str | None
  location_text  : str | None
  link_tracking  : str | None                 # exactly as found
  raw_block      : str                        # the text/HTML fragment it was read from
  part           : "html" | "text"

Problem
  where    : str        # part and position, e.g. "html block 3"
  expected : str        # e.g. "listing code in block"
  found    : str        # short excerpt of the raw evidence
```

## Rules

- MUST NOT make any network request or follow any link.
- MUST NOT infer a value: a field not literally present is `None`.
- MUST raise nothing for unexpected layouts; it reports them as `problems`. An email whose layout is
  not recognised at all returns `alert_type = "new_listings"` with zero listings and one problem
  `expected: "known new-listing layout"`, which the caller records as `failed`.
- When both HTML and text parts carry listings, the reader returns blocks from both; the caller
  compares them by `listing_code` (FR-017).
- `reader_version` changes whenever the reading rules change, so stored outcomes can be re-processed.
- Every supported layout has at least one fixture in `tests/fixtures/emails/` and a test asserting
  the exact `ReadResult` for it (FR-022).

## Caller outcome mapping

| ReadResult | Email outcome |
|---|---|
| `not_idealista` | `rejected` — "not a recognised alert email" |
| `other_idealista` | `rejected` — "unsupported alert type" |
| `new_listings`, ≥1 listing, problems for some blocks | `imported`; each problem listed in the summary |
| `new_listings`, 0 listings | `failed` — reason from the problems |
