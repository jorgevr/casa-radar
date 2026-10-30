# T019 dev: import-emails command

File changed: `app/cli.py` only. No automated tests for T019, by the user's decision (covered by quickstart §2,
verified manually below).

## What changed
- Subparser `import-emails PATH [PATH ...]`; calls `alerts.import_paths(conn, [Path(p) ...])` (kind `file_cli`).
- `format_import_summary(summary)` (plus tiny helpers `_plural`, `_cut`, `_problem_line`) builds the lines of
  contracts/cli.md: one line per problem (`FALLO` failed, `RECHAZADO` rejected), one per notice (`AVISO`), then the
  emails totals line and the listings line. Printed with `print(*lines, sep="\n")`.
- Exit code 1 if `n_failed > 0`, else 0. The "Última sincronización correcta" line is not printed (belongs to sync).
- Module docstring usage list updated.

## Manual run (isolated env: CASA_DB/CASA_NEEDS/CASA_APPDATA under %TEMP%\casa-agent-T019, empty db)
```text
> python -m app.cli import-emails tests/fixtures/emails        (exit 0)
RECHAZADO 2021-03-10 ¡Nuevo piso en tu búsqu…  tipo de alerta no soportado
12 emails: 11 importados, 0 ya procesados, 1 rechazado, 0 fallidos
anuncios: 11 nuevos, 0 actualizados (0 cambios de precio)
> second run                                                    (exit 0)
12 emails: 0 importados, 12 ya procesados, 0 rechazados, 0 fallidos
anuncios: 0 nuevos, 0 actualizados (0 cambios de precio)
> import-emails <missing>.eml <temp>\x.msg                      (exit 1)
FALLO     sin fecha  nope.eml                  unreadable file: expected an .eml or .mbox file
FALLO     sin fecha  x.msg                     unsupported file format: save as .eml
2 emails: 0 importados, 0 ya procesados, 0 rechazados, 2 fallidos
anuncios: 0 nuevos, 0 actualizados (0 cambios de precio)
```

## Decisions the docs don't cover
- Plurals: singular only for exactly 1 (`1 rechazado`, `1 ya procesado`, `1 nuevo`, `1 cambio`); 0 and n>1 plural.
- Line layout: label padded to 9, date `YYYY-MM-DD` (first 10 chars of `alert_date`), subject whitespace-collapsed and
  cut to 24 chars with `…` and padded, two spaces, reason. `None` date prints `sin fecha`; `None` subject falls back
  to `email_id` (the file name for file-level failures). Reasons are printed as the alerts module gives them
  (file-level ones are in English there).
- Missing path: handled by `import_paths` (counts as 1 found + 1 failed, reason "unreadable file..."), so it is
  reported and gives exit 1. The CLI adds no separate check, so a missing path and an unreadable file look alike.
- Listings line: the contract's "N anuncios ... sin cambios" cannot be derived (the summary has only
  `n_new_listings`, `n_updated_listings`, `n_price_changes`; no total or unchanged count). I print
  `anuncios: X nuevos, Y actualizados (Z cambios de precio)` and omit the leading N and "sin cambios".
  The line is always printed, also with zeros.
- Exit codes: 0 / 1 only (2 and 3 belong to sync). An unexpected exception in `import_paths` propagates (run is
  marked failed there).
- Note: "11 nuevos" for 11 imported emails is the summary's `n_new_listings` as stored; not re-derived.

## Reviewer checks
- The listings line never invents a figure; `sin cambios` really absent.
- No file content is printed other than subject, reason, notice text, file name.
- `git diff` touches only `app/cli.py` besides this handoff; existing commands unchanged.
- Gates: compileall 0; not slow 94 passed; slow 1 passed; anonymise check exit 0.
