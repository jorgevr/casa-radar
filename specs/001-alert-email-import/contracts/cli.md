# Contract: Command line

Added to `python -m app.cli`. Output text is Spanish, like the existing commands.

## `import-emails PATH [PATH ...]`

Imports `.eml` and `.mbox` files; a folder means every such file inside it (not recursive).

Output (one line per problem, then the summary):

```text
FALLO     alerta-2026-10-20.eml  html bloque 3: se esperaba "código de anuncio", encontrado "…"
RECHAZADO newsletter.eml         no es un email de alerta reconocido
RECHAZADO bajada.eml             tipo de alerta no soportado
29 emails: 26 importados, 1 ya importado, 2 rechazados, 0 fallidos
41 anuncios: 12 nuevos, 3 actualizados (2 cambios de precio), 26 sin cambios
```

Exit code: 0 if no email failed; 1 if any failed (rejected emails do not change the exit code).

## `reprocess-emails [--failed | --all]`

Re-runs the current alert reader over stored emails (default `--failed`). Same output format.
Works without the original files (US3-3).

## Unchanged

`import-listings`, `serve` and the rest keep their current behaviour.
