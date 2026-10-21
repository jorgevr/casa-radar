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
config/needs.yaml your needs and weights        tests/   23 tests
```
