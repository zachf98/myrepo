# ncscout

Daily screening of US land listings for **natural capital** — the productive
capacity actually present on the ground — and the investment case that capacity
supports.

Every parcel is scored against federal geospatial data: soil productivity,
rainfall, surface water, solar irradiance, wind, land cover, terrain, flood and
wildfire hazard. The output is a ranked shortlist under a price ceiling, with
the measurement behind every score and the caveats that apply.

```bash
pip install -e .
ncscout scan --source fixtures --top 10
```

Reports land in `reports/` as Markdown, HTML, JSON and CSV.

---

## Read this before you rely on it

**Zillow cannot be scraped, and this tool does not try.**

Zillow's `robots.txt` explicitly disallows `/homes/` and `/api/` — exactly the
search and listing endpoints — and its
[Terms of Use](https://www.zillow.com/corp/Terms.htm) prohibit automated data
extraction. A scraper would be rate-limited and blocked quickly, and it would
put you on the wrong side of those terms. That is not a good foundation for
something you check every morning.

So listing access is a pluggable adapter, and the durable asset is the scoring
engine, which works on any listing carrying a price, an acreage and a location:

| Source | Status | How to get it |
|---|---|---|
| `bridge` | Zillow Group's own API | Apply at [bridgedataoutput.com](https://bridgedataoutput.com), get MLS approval, set `BRIDGE_API_TOKEN` |
| `reso` | Any RESO Web API feed | Most MLSs and aggregators expose one; usually easier to obtain than a Zillow dataset. Set `RESO_BASE_URL` + `RESO_ACCESS_TOKEN` |
| `fixtures` | Works now, no credentials | Synthetic listings at real coordinates, for testing and demos |

`ncscout sources` shows which are configured. Adding another feed means one
class implementing `search()` — see `src/ncscout/sources/base.py`.

**The fixtures are not real listings.** They are invented prices and acreages
placed at real US coordinates, so all the enrichment and scoring runs against
genuine federal data. They let you evaluate the model before paying for a feed.
They are not deals.

---

## What natural capital means here

Seven weighted components, each traceable to a measurement:

| Component | Weight | Measures | From |
|---|---|---|---|
| Water | 22% | Precipitation, distance to perennial water, soil water storage | NASA POWER, USGS NHD, SSURGO |
| Soil | 20% | NCCPI productivity index, water storage, slope | USDA NRCS SSURGO |
| Timber | 13% | Forest cover, growth potential | NLCD 2021, NASA POWER |
| Solar | 12% | Global horizontal irradiance | NASA POWER |
| Resilience | 15% | Flood zone, wildfire hazard, aridity (deductive) | FEMA NFHL, SSURGO, derived |
| Climate | 10% | Growing degree days | NASA POWER |
| Wind | 8% | 50 m wind speed | NASA POWER |

Weights and every breakpoint curve live in
[`config/scoring.yaml`](config/scoring.yaml). Change your thesis by editing
config, not code.

### Scores carry their provenance

Each measurement records whether it was **measured** (SSURGO soil survey),
**modeled** (NASA POWER reanalysis) or **missing**, and confidence propagates to
the parcel level. Confidence answers two questions at once: how good the
resolved data is, and how much of the intended weight resolved at all — so a
parcel with two of seven components populated cannot report high confidence. A
missing dataset lowers confidence and renormalises the remaining weights, rather
than dragging a score toward zero and hiding a good parcel.

Low-confidence parcels are flagged in the report, and the composite score is
damped by confidence so a thinly-measured parcel does not outrank a
well-measured one on equal merit.

---

## What the investment model does

Each revenue stream is gated on the preconditions it actually needs, and charged
only against the acres that can host it:

- **Timber** — forested acres only, annual increment scaled by site productivity
- **Row crop lease** — croppable cover, NCCPI above threshold, slope under 12%
- **Grazing** — rangeland acres, forage from growing-season moisture
- **Solar lease** — open, near-flat acres above an irradiance floor
- **Wind lease** — 50 m wind speed above 6.5 m/s, turbine count from spacing
- **Hunting lease** — whole parcel; coexists with timber rather than displacing it
- **Carbon** — forested acres, net of verification and monitoring overhead
- **Agritourism** — derived scenery score from relief, cover and water

Then: net operating income after carrying costs, cap rate, simple payback,
10-year NPV and IRR.

Three rules keep the numbers from inflating:

1. **Acres are allocated, not reused.** A 150-acre parcel that is 30% pasture
   gets row-crop rent on 45 acres, not 150. Skipping this is the easiest way to
   manufacture a fake cap rate — during development it produced a 24.9% cap rate
   on a Maine spruce tract before the allocation was added.
2. **Competing uses do not stack.** Only the strongest use of the open portion,
   and of the forested portion, survives.
3. **Third-party-dependent income is discounted.** A solar developer signing a
   lease or a registry issuing credits are probability-weighted and flagged
   speculative. The report states when most of a parcel's modelled income is
   speculative.

---

## Usage

```bash
# Scan and write reports
ncscout scan --source fixtures --top 10

# Real feed, once credentials are set
ncscout scan --source bridge --top 10 --limit 800

# Score a single parcel by coordinate: the fastest way to sanity-check the model
ncscout explain 38.301 -80.098 --price 148000 --acres 62

# Which sources are configured
ncscout sources
```

Useful flags: `--prescreen N` (how many survive to full enrichment),
`--formats md,html,json,csv`, `--config path.yaml`, `--no-cache`, `--workers N`,
`--verbose`.

### Cost control

Full enrichment is about 20 requests per parcel against public services that
should not be hammered. Scanning 500 listings that way would be ~10,000
requests for a top-10 answer, nearly all spent on parcels that were never going
to place.

So a scan runs in two stages. Stage one spends **one** request per listing on
climate, which alone separates productive from marginal ground, and combines it
with price efficiency against the cohort median. Only the survivors
(`--prescreen`, default 60) get soil, water, land cover, flood and terrain.
Responses are cached on disk, so a same-day re-run costs nothing.

---

## Daily automation

[`.github/workflows/daily-scan.yml`](.github/workflows/daily-scan.yml) runs at
11:00 UTC, writes the report to the job summary, uploads it as an artifact, and
commits it to `reports/` for history. Add listing credentials as repository
secrets; the geospatial datasets need none.

Set the `NCSCOUT_SOURCE` repository variable to switch off fixtures once you
have a feed. To run it anywhere else, the whole thing is one command — cron,
Lambda on a schedule, or a container all work.

---

## Data sources

All free, all public, none requiring a key:

- **USDA NRCS SSURGO** via Soil Data Access — NCCPI, available water storage,
  slope, observed flood frequency
- **NASA POWER** — precipitation, temperature, growing degree days, irradiance,
  50 m wind
- **NLCD 2021** via MRLC — land cover, sampled on concentric rings across the
  parcel footprint
- **USGS NHD** — perennial streams and waterbodies at expanding radii
- **FEMA NFHL** — regulatory flood zones
- **USGS 3DEP** — elevation and local relief
- **US Census geocoder** — addresses to coordinates

Two deliberate substitutions:

- **NREL** would be the better solar and wind source, but its API was
  unreachable from the target environment, so NASA POWER covers both.
- **USFS Wildfire Hazard Potential** returns 403 to unauthenticated clients, so
  wildfire class is derived from the fire-behaviour triangle — fuel type from
  NLCD, aridity from precipitation and temperature, slope from SSURGO. It costs
  no extra requests and is always available, and it is recorded as modeled,
  never measured. Swap in an authenticated WHP service to override it.

---

## Limitations

The screen cannot see: **legal access and easements**, **mineral and water
rights severance**, **title defects**, **zoning and permitted use**, wetland
delineation, utility availability, or true parcel boundaries. Any one of these
can make a top-ranked parcel worthless. Coordinates are treated as a point and
sampled around, so a large parcel's internal variability is approximated.

Revenue assumptions are national approximations from config, not local quotes.
Lease rates vary several-fold by county.

This produces a shortlist worth a phone call. It is not an appraisal and not
investment advice.

---

## Development

```bash
pip install -e ".[dev]"
pytest -m "not live"      # 81 offline tests
pytest -m live            # verifies the federal APIs still respond as expected
ruff check src tests
```

The live tests exist because the dangerous failure here is silent: a federal
service renames a field, every enricher degrades to `MISSING`, and the scan
keeps producing confident-looking reports built on nothing. They assert known
values — Iowa soil must rate above 0.5 NCCPI, Appalachian soil below 0.4 — so
drift is caught. Run them when coverage looks suspiciously low.

### Layout

```
src/ncscout/
  sources/    listing adapters (bridge, reso, fixtures)
  enrich/     one module per dataset; failures isolated per enricher
  scoring/    natural_capital, business, composite
  report/     markdown, html, json, csv
  pipeline.py two-stage scan orchestration
config/scoring.yaml   all weights, curves and economic assumptions
```
