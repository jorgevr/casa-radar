# FU4 dev: malformed rules outside import_paths

Changed: `app/alerts.py` only. In `process_message`, when `rules is None` it now calls `categories.load_rules()`
and falls back to `[]` on ValueError (category 'unknown', matched '[]'), so a caller that does not pass rules
never loses an email. `categories.categorise(text)` is unchanged and still raises (the CLI relies on it).

Gates: compileall ok; pytest -m "not slow" 359 passed; anonymise check ok; diff lists only the FU4 tests and
handoff; requirements.txt unchanged.

For the Phase 9 sync task: load rules once per run (not per message; this fallback re-reads the file per
message), pass them to `process_message`, and on ValueError record the error in `import_runs.error` as
`import_paths` does. This fallback is only a safety net and does not report the error.
