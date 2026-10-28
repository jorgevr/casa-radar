# Contract: Command line

Added to `python -m app.cli`. Output text is Spanish, like the existing commands. Secrets are never
printed.

## `mailbox-setup [--label NAME]`

Runs the authorisation flow ([mail-source](mail-source.md#authorisation-flow-setup-and-re-authorise)),
prints the account and asks for the label if `--label` is absent. Also used to re-authorise.

```text
Cuenta: usuario@gmail.com
Carpeta: Idealista (id Label_12)
Permiso: solo lectura de Gmail, revocable en myaccount.google.com/permissions
```

## `sync [--wait]`

Runs one sync now (same function as the schedule). Prints the summary below. Exit code 0 if the sync
finished and no email failed; 1 if an email failed; 2 if the sync stopped (auth, folder, network);
3 if a sync is already running.

## `import-emails PATH [PATH ...]`

Imports `.eml` and `.mbox` files; a folder means every such file inside it (not recursive). No network
connection. Same summary and exit codes 0/1.

## `reprocess-emails [--failed | --all]`

Re-runs the current reader over stored emails (default `--failed`), without files or mailbox.

## `categories`

Prints the category rules and, for each stored search name, the category it gets now.

## Summary format (all commands)

```text
FALLO     2026-10-20 ¡Bajada de precio…  precio de la tarjeta 640.000 ≠ "a 645.000€"
RECHAZADO 2021-03-10 ¡Nuevo piso en…     tipo de alerta no soportado
AVISO     2026-10-27 ¡Nuevo piso en…     atributo no reconocido: "2 baños"
31 emails: 26 importados, 1 ya procesado, 3 rechazados, 1 fallido
28 anuncios: 12 nuevos, 3 actualizados (2 cambios de precio), 13 sin cambios
Última sincronización correcta: 2026-10-28 11:45
```

## Unchanged

`import-listings`, `serve` and the rest keep their behaviour; `serve` now also runs the 15-minute
schedule when the mailbox is configured.
