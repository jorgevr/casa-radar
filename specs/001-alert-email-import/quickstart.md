# Quickstart: validating alert-email import

Run guide that proves the feature end to end. Contracts: [cli](contracts/cli.md),
[api](contracts/api.md), [alert reader](contracts/alert-reader.md). Data: [data-model](data-model.md).

## Prerequisites

- `pip install -r requirements.txt` (no new packages for this feature).
- Anonymised Idealista new-listing alert samples in `tests/fixtures/emails/` (at least one per
  layout; include one forwarded and, if they exist, one HTML-only and one text-only).
- Optional: `config/private_terms.txt` (untracked) with your name, street and phone, used by the
  fixture privacy check.
- `data/` is untracked (prerequisite task), so nothing below can reach the repository.

## 1. Offline test suite

```bash
python -m pytest -q
```

Expected: all tests pass, including
- fixture privacy check (FR-024) — fails if a sample contains a real address, account token or a
  private term;
- golden tests for duplicate thresholds (3 % / 5 % boundaries), unknown-field flags and the
  zone-less median fix, citing the hand calculation in the test (Article VII);
- import tests run with outbound connections disabled (SC-006);
- import of the fixture set in < 5 s (SC-001).

## 2. Import from the command line

```bash
python -m app.cli import-emails tests/fixtures/emails
python -m app.cli import-emails tests/fixtures/emails      # second run
```

Expected: the first run prints the summary with counts that add up to the number of files
(SC-004); the second reports every email as already imported and 0 new listings (SC-003).

## 3. Check the ranked list

```bash
python -m app.cli serve
```

Open http://127.0.0.1:8765 → Oportunidades. Expected for imported listings:
- price, area, bedrooms, zone (or "zona no reconocida" + original text), link, detection date =
  alert date, source "Idealista (email de alerta)";
- bathrooms, floor, elevator, terrace, garage, pool, garden, location shown as "desconocido";
- `<field> unknown` flags where a hard filter could not be checked;
- ≥ 95 % of fixture listings show price, area and link (SC-002).

## 4. Price change, duplicates, removal

- Import a fixture where a known listing reappears with a later date and lower price → current price
  updated, both prices in history, price-drop flag shown.
- Add a CSV row with the same zone/type/bedrooms and area/price within 3 %/5 % of an alert listing →
  both show "posible duplicado de …"; merging from the UI leaves one row with both links.
- Mark a listing "ya no disponible" → it stays visible, marked; undo restores it.

## 5. Failure path

- Put a non-Idealista email and a truncated alert into a temp folder and import it → summary lists
  them as rejected / failed with reasons; `GET /api/alerts/emails?outcome=failed` lists the failed
  one; `python -m app.cli reprocess-emails` re-runs it without the file.

## 6. Clean up demo data

Delete `data/casa.db` if you imported fixtures into your real database.
