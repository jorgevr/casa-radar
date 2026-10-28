# Quickstart: validating alert-email import

Run guide that proves the feature end to end. Contracts: [cli](contracts/cli.md),
[api](contracts/api.md), [alert reader](contracts/alert-reader.md),
[mail source](contracts/mail-source.md). Data: [data-model](data-model.md).

## Prerequisites

- P0 done: `git ls-files data config/needs.yaml` prints nothing; `config/needs.example.yaml` exists.
- `pip install -r requirements.txt` (no new packages for this feature).
- Fixtures in `tests/fixtures/emails/` (12 anonymised alerts); originals kept outside the repository.

## 1. Offline test suite (no mailbox, no network)

```bash
python -m pytest -q
```

Expected: all tests pass, including
- fixture privacy check (FR-024): `anonymise_eml.py --check` over the fixture folder;
- reader tests: exact `ReadResult` per fixture (resale, development, price drop, 2021 = unsupported);
- derivation tests: same listings, prices, history, published and updated dates whatever the
  processing order (permutations of the fixtures);
- Gmail client tests against `httpx.MockTransport`: only `gmail.readonly` requested, only the four
  allowed GET calls, label id on every list call, `invalid_grant` → `AuthRevoked`, no token value in
  logs or errors;
- sync loop tests with the fake mail source: backfill window, incremental skip, interruption and
  resume, revoked → paused, folder missing, concurrent "sync now" → refused;
- golden scoring tests (Article VII): duplicate thresholds at 3 %/5 % boundaries, unknown-field
  flags, zone-less medians, development exclusions, each citing its hand calculation;
- all import/sync tests run with socket creation disabled (SC-006); fixture import < 5 s (SC-001);
  1,000-email fake backlog < 10 min (SC-010).

## 2. File import from the command line

```bash
python -m app.cli import-emails tests/fixtures/emails
python -m app.cli import-emails tests/fixtures/emails      # second run
```

Expected (first run): 12 emails = 11 imported + 1 rejected (2021 layout, "tipo de alerta no
soportado"); the counts add up (SC-004). Listings 112842548 (Torrejón), 112692121 (Alcalá) and
112658090 (Tres Cantos) come only from price drops: published date "unknown", history shows
"before <date>" and the new price. Second run: 12 already processed, 0 new listings (SC-003).

## 3. Mailbox setup (real account, manual, once)

1. Google Cloud console: create a project, enable the Gmail API, OAuth consent screen *External*,
   publishing status **In production** (Testing would expire the authorisation every 7 days),
   create an OAuth client of type *Desktop app*, download its JSON.
2. Save it as `%LOCALAPPDATA%\casa-radar\client_secret.json`. Check: `git status` shows nothing new.
3. In Gmail, create a filter `from:noresponder@idealista.com` → apply label `Idealista`.
4. `python -m app.cli mailbox-setup --label Idealista`; approve in the browser (continue past
   "Google hasn't verified this app": it is your own project).
5. `python -m app.cli sync`. Expected: the last 30 days of alerts processed; summary printed.

Check the permission: <https://myaccount.google.com/permissions> lists the app with "read your
email" only. In Gmail, the synced alerts keep their unread state (SC-009).

## 4. Ranked list

```bash
python -m app.cli serve
```

Open http://127.0.0.1:8765 → Oportunidades. Expected:
- header shows the last successful sync and no warning; "Sincronizar ahora" works;
- each listing: price, area, bedrooms, zone (or "zona no reconocida" + text), link, published and
  updated dates, "encontrado vía: …", source "Idealista (email de alerta)";
- clicking *Publicado* or *Actualizado* sorts by that date, unknown last (FR-036);
- developments (Brunete, Daganzo) show "precio de promoción, no de una vivienda" and no
  affordability until a unit is entered;
- unknown fields read "desconocido"; hard filters on unknown fields are flags, not exclusions.

## 5. Failure paths

- Revoke the app at myaccount.google.com/permissions, press "Sincronizar ahora" → "sincronización
  detenida: permiso revocado" with the re-authorise steps; automatic sync paused; out-of-date warning.
  Run `mailbox-setup` again → sync resumes.
- Disconnect the network and wait for a scheduled sync → error and its time shown; warning after
  30 minutes; reconnect → next sync succeeds.
- Rename the Gmail label → "carpeta Idealista no encontrada"; nothing else read.

## 6. Clean up

Delete `data/casa.db` if you imported fixtures into your real database. To stop mailbox access
completely: "Desconectar" in Datos, then revoke at myaccount.google.com/permissions.
