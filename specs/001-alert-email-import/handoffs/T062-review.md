# T062 review

**Status: [PASS]**

Scope: `git diff main...HEAD` touches only `README.md` and `handoffs/T062-dev.md`. No code, config, secrets or `.eml`.

## Checked against docs and code
- [OK] README.md:25-27 `import-emails PATH [PATH ...]`, `reprocess-emails [--failed | --all]` (default `--failed`) — matches contracts/cli.md and app/cli.py:245-249. Not recursive, exit 0/1: contracts/cli.md.
- [OK] README.md:34-47 `mailbox-setup --label Idealista`, `sync [--wait]`, exit codes 0/1/2/3, first sync 30 days — app/cli.py:254-255, contracts/cli.md, research.md:78. Re-authorise by rerunning: contracts/cli.md, data-model.md:155.
- [OK] README.md:33,37 "In production", "Desktop app", filter `from:noresponder@idealista.com` → label `Idealista`, "Google hasn't verified this app" — quickstart.md:49-54, research.md:31-40. Only the label-filter address appears; no personal data.
- [OK] README.md:19-22 needs.example.yaml → needs.yaml; "the app also does it when the file is missing" — app/db.py:103. `config/needs.yaml` and `data/` ignored (.gitignore:9,12).
- [OK] README.md:52 `%LOCALAPPDATA%\casa-radar\`, `client_secret.json`, `token.bin` DPAPI, non-Windows `token.json` unencrypted — research.md:62-65, data-model.md:170. `client_secret*.json`/`token*.json` ignored (.gitignore:5-6). `token.bin` is not matched by the ignore, but it lives outside the repo and README doesn't claim otherwise.
- [OK] README.md:55 "Desconectar" in Datos (app/static/index.html:280), then revoke at myaccount.google.com/permissions (quickstart.md:87); text "sincronización detenida: permiso revocado" (quickstart.md:77-78).
- [OK] README.md:49 15-minute sync when mailbox configured (research.md:96, plan.md:12); "Sincronizar ahora" (index.html:325); unread preserved (quickstart.md:58, SC-009).
- [OK] README.md:57 "only `oauth2.googleapis.com` and `gmail.googleapis.com`" — research.md:121-122. Auth page `accounts.google.com` is opened in the user's browser, not by the tool (research.md:120), so the claim holds. README.md:32 says `gmail.readonly`; consistent with constitution/mail-source.md:29.
- [OK] README.md:88 `tests/   test suite` replacing `23 tests`: 23 was stale (repo now has about 421 `def test_` functions), so a count-free label is accurate.
- [OK] Text integrity: UTF-8, no mojibake. PowerShell hint README.md:22 reads `# PowerShell: Copy-Item config\needs.example.yaml config\needs.yaml` — valid; no duplicate/garbled line from the two "fix PowerShell copy hint" commits.

## Findings (non-blocking)
- README.md:32 The CLI/UI flow also lets `mailbox-setup` prompt for the label when `--label` is omitted (contracts/cli.md); README only documents `--label`. Not an inaccuracy.
- README.md:52 `client_secret*.json and token*.json are git-ignored` does not mention `token.bin`; harmless as it is outside the repo.
- Mixed CRLF/LF line endings in README.md (pre-existing style, not a content issue).

No gates run (docs-only review; nothing network or mailbox executed).
