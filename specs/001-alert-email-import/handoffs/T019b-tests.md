# T019b tests: console encoding of import-emails

File: `tests/test_cli_import.py` (new). Nothing under `app/` or `tests/conftest.py` touched. All tests use `no_network`
and replace `sys.stdout` with a real `io.TextIOWrapper(BytesIO, encoding=..., errors="strict")`, then decode the bytes.

1. `test_cp1252_stdout_unencodable_subject_keeps_summary_and_exit_0`: a non-Idealista .eml (built in tmp_path with
   `EmailMessage`, subject `Oferta ≠ casa 🏠`) imported into cp1252 stdout. Asserts no exception, exit code 0, the totals
   line `1 email: 0 importados, 0 ya procesados, 1 rechazado, 0 fallidos`, and `RECHAZADO` and `Oferta` present. The
   replacement for unencodable characters is not pinned. FAILS now: `UnicodeEncodeError: 'charmap' codec can't encode
   character '\u2260'` raised from `print` at app/cli.py:90 (the bug).
2. `test_cp1252_stdout_fixture_folder_totals`: fixture folder into cp1252 stdout, exit 0 and
   `12 emails: 11 importados, 0 ya procesados, 1 rechazado, 0 fallidos` (Phase 3 Independent Test). PASSES now (all
   fixture text is cp1252-encodable); guards against the fix breaking normal output.
3. `test_utf8_stdout_keeps_characters_intact`: fixture folder into utf-8 stdout; asserts exit 0 and
   `RECHAZADO 2021-03-10 ¡Nuevo piso` appears intact (the rejected 2021 fixture is the only fixture subject that gets
   printed). PASSES now; ensures the fix does not degrade capable consoles.

Results: new file 1 failed (test 1), 2 passed; rest of suite `-m "not slow"` 94 passed.
Reviewer note: `…` in the fixture subject is truncation by the app and is cp1252-encodable; only `¡` is asserted.
