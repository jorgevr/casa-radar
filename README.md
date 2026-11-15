# Casa Radar

Local app to rank houses/flats against **your needs**, in the areas you care about. Python + SQLite + one HTML page. Nothing leaves your machine except the calls to the data sources you enable.

```bash
cd casa-radar
pip install -r requirements.txt
python -m app.cli serve            # http://127.0.0.1:8765
```
Then: **Necesidades** (income, savings, rate, min m²/bedrooms) → **Datos** (import listings) → **Zonas** (notary €/m², indicators) → **Oportunidades**.
Demo data: `python -m app.cli import-listings samples/listings.csv && python -m app.cli import-indicators samples/indicators.csv` (rows are labelled EJEMPLO; delete `data/casa.db` afterwards).
Tests: `python -m pytest -q`.

## Alert-email import (Idealista)

Listings can come from Idealista **alert emails**, either from files or straight from your Gmail. Nothing is scraped: only the email text is read, links are never followed and images never downloaded. Unknown fields stay "desconocido".

### First run: needs file
`config/needs.yaml` is yours and is not tracked by git. Copy the template once (the app also does it when the file is missing):
```bash
cp config/needs.example.yaml config/needs.yaml
# PowerShell: Copy-Item config\needs.example.yaml config\needs.yaml
```
`data/` (the SQLite database) is untracked too.

### Import from files (no network)
```bash
python -m app.cli import-emails PATH [PATH ...]    # .eml / .mbox files, or a folder (not recursive)
python -m app.cli reprocess-emails [--failed | --all]   # re-run the current reader over stored emails (default --failed)
```
Both print a summary (imported / already processed / rejected / failed emails; new / updated listings). Exit codes of `import-emails`: 0 ok, 1 an email failed. Re-importing the same files adds nothing.

### Connect your mailbox (manual, once)
Read-only access (`gmail.readonly`) to one Gmail label.
1. In the Google Cloud console create a project, enable the **Gmail API**, configure the OAuth consent screen as *External* and set the publishing status to **In production** (in *Testing* the authorisation expires every 7 days). Create an OAuth client of type **Desktop app** and download its JSON.
2. Save it as `%LOCALAPPDATA%\casa-radar\client_secret.json`.
3. In Gmail create a filter `from:noresponder@idealista.com` → apply label `Idealista`.
4. Authorise:
   ```bash
   python -m app.cli mailbox-setup --label Idealista
   ```
   Approve in the browser; continue past "Google hasn't verified this app" (it is your own project). Run the same command again to re-authorise.
5. Sync:
   ```bash
   python -m app.cli sync [--wait]
   ```
   The first sync reads the last 30 days. Exit codes: 0 ok, 1 an email failed, 2 sync stopped (auth, label, network), 3 a sync is already running.

While `serve` runs and the mailbox is configured, a sync also runs every 15 minutes; "Sincronizar ahora" in the UI runs one on demand. Synced emails keep their unread state in Gmail.

### Where secrets live
Outside the repository, in `%LOCALAPPDATA%\casa-radar\`: `client_secret.json` (copied by you) and `token.bin` (refresh token, encrypted with Windows DPAPI for your user). On non-Windows systems the token is `token.json` with owner-only permissions and **not encrypted**. Secrets are never printed or logged; `client_secret*.json` and `token*.json` are git-ignored.

### Revoke access
Press "Desconectar" in the **Datos** tab, then remove the app at <https://myaccount.google.com/permissions>. If you revoke from Google first, the next sync shows "sincronización detenida: permiso revocado" and pauses until you run `mailbox-setup` again.

Outbound calls of this feature go only to `oauth2.googleapis.com` and `gmail.googleapis.com`. Tests never touch the network.

## How it scores (0–100)
`price` (asking €/m² vs reference) · `affordability` (mortgage effort vs your ceiling, with +1/+2 pp rate stress) · `neighbourhood` (percentile of zone indicators) · `amenities` (distance to park/school/health/transit/supermarket) · `fit` · `momentum` (price drops). Weights live in `config/needs.yaml`.
Rules the code enforces: missing data is **dropped and the weights renormalised**, never scored as average; every listing shows a `coverage` figure and a list of flags saying what the score is *not* based on; hard filters mark listings *excluded* with reasons instead of hiding them.

## Sources: what is wired, what is not
| Source | Status | Notes |
|---|---|---|
| **Idealista** via `galimru/idealista-mcp` | Client written and tested against a fake MCP server; **not tested against the real one** | Needs Idealista API credentials (client key/secret + signing secret) that only Idealista can issue. Run `python -m app.cli mcp-schema`, copy the real argument names into `config/providers.yaml`. If the response shape differs the parser raises with the raw payload instead of guessing. |
| **Manual / CSV listings** | Works now | Use this until the Idealista credentials exist. |
| **SERPAVI** rent €/m² (Ministerio de Vivienda, via the catalog) | Loader tested on a synthetic workbook built from the catalog's description; **not run on the real 71 MB file** | `python -m app.cli serpavi --file <xlsx>`. Fails loudly, printing columns, if the layout differs. |
| **Madrid open data (CKAN)** | Paging/retry client tested with a mock; no indicator extraction yet | Use `app/etl/madrid_ckan.py` to pull padrón/air quality, map the fields, then load with `import-indicators`. Field names must be checked on first use. |
| **Notariado €/m²** | **No API exists that I could find** — the portal is a JS map | Enter the figure per zone (Zonas tab or CSV) as `notary_price_m2_flat` / `_house`. |
| **Notariado mortgage tool** | Not wired | Page is a JS form. `app/mortgage.py` computes the payment itself (French amortisation, ITP/AJD/IVA/costs from config). Compare against the Notariado tool once to validate. |
| **OpenStreetMap (Overpass)** | Not in your list; added because nothing there gives point-to-point distances | Per listing, cached, needs lat/lon. Parser tested on fixtures, not against the live endpoint. |

## Things you should know before trusting a ranking
1. **Safety is the weakest signal.** The Interior ministry publishes crime by municipality only (district level isn't available from that source). `crime_rate` is a municipal proxy.
2. **Asking vs notarial prices differ.** Notary figures are closing prices. Set `market.asking_markup` once you see the *implied markup* column in Zonas.
3. **Without a notary price**, the app compares a listing to the median of *your own* listings in that zone (≥5 needed) and flags the selection bias.
4. **Zones need at least two with data** for neighbourhood percentiles to mean anything.
5. Tax defaults are the Comunidad de Madrid general rates; the bank's actual offer will differ. Treat output as a screening estimate.
6. Geography is municipality-level except Madrid city (per district), so Alcorcón or Alcobendas are one zone each. SERPAVI/INE also publish census-section data if you later want finer.

## Layout
```
app/mortgage.py   payment, taxes, savings shortfall, stress   app/scoring.py   zone + listing scores, flags
app/listings.py   normalisation, zone assignment, price history
app/providers/    idealista_mcp.py (stdio JSON-RPC), csv_import.py
app/etl/          serpavi.py, overpass.py, madrid_ckan.py, indicators.py (CSV + Madrid districts)
config/needs.yaml your needs and weights        tests/   test suite
```
