# T019b dev: printable import-emails output

File: `app/cli.py` only (3 lines, in the `import-emails` branch, before the summary `print`).

Change: `if hasattr(sys.stdout, "reconfigure"): sys.stdout.reconfigure(errors="backslashreplace")`. Only the error
handler changes, never the encoding, so a UTF-8 console still shows `¡ … ≠` intact. It runs only for
`import-emails`; other commands are untouched. The exit code still depends only on `n_failed`.

Decision, backslashreplace vs replace: `replace` turns `≠`/emoji into `?`, hiding what was there. `backslashreplace`
prints `≠` / `\U0001f3e0`, so the user can still see which character was dropped (Article VI: no silent loss).
Tests do not pin the replacement, so either satisfies them.

Reviewer should check:
- streams without `reconfigure` (e.g. a custom writer) are skipped by the guard and print as before;
- the reconfigure happens after the import, so it cannot affect the import itself;
- the encoding fix applies to the summary only; error text printed elsewhere is out of scope.

Gates: compileall OK; `-m "not slow"` and `-m slow` results reported in the chat handoff; anonymise check exit 0;
real piped run of the fixture folder: 12 emails, 11 importados, 1 rechazado, 0 fallidos, exit 0.
