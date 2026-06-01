# BI site design — table builder + prebuilt viz (Phase 5)

## Premise

USAspending.gov is a **lookup** tool (retrieve a vendor's/award's records). Ours inverts
that: **aggregation is the product**. Two surfaces:

1. **Table Builder** — a pivot/crosstab constructor (modeled on OPM's
   [table-builder](https://data.opm.gov/explore-data/data/table-builder)) where a user
   picks dimensions, metrics, and filters to build any breakdown — with **shareable URLs**
   and a **period-over-period comparison** mode OPM doesn't have.
2. **Prebuilt visualizations** — a set of curated, ready-made charts/dashboards for the
   common questions (spend over time, top agencies, geographic map, NAICS/PSC, competition).

The record-level table is a **drill-down**, reached after building/slicing — not the centerpiece.

## Table Builder (the flexible core)

OPM's 5-step progressive flow, adapted + extended:

1. **Dataset** — Contracts | Assistance, and **transaction-level vs award-level**
   (award-level uses the award-summary table).
2. **Timeframe** — a date range; **or two periods (A vs B)** for comparison (the differentiator).
3. **Table elements** — **Rows** (required) + **Columns** (optional) + **Metrics**:
   - Rows/Columns = any dimension (agency, sub-agency, recipient, recipient parent, NAICS,
     PSC, CFDA, state, county, congressional district, country, award type, extent_competed,
     set-aside, pricing type, DEFC, fiscal year/month).
   - Metrics = obligations, outlays, transaction count, **distinct award count**,
     avg award size, **distinct vendors (nonzero-net)**. In period mode each metric expands
     to **A, B, Δ, %Δ**.
4. **Filters** — multi-select on any dimension + amount/date ranges. Coded dimensions show
   **codebook labels** (extent_competed → "NOT COMPETED"); the dimension/filter picker is
   grouped by the dictionary's 12 groupings with hover-definitions.
5. **Generate** → crosstab table (heatmap shading), **CSV export**, and a **copyable URL**
   that fully encodes the build (dataset, periods, rows/cols/metrics, filters) so it round-trips.

## Prebuilt visualizations

Curated cards under the same global filters, each click-through to the builder:
spend over time (line), top agencies/recipients (bar), geography (choropleth), NAICS/PSC
(treemap), competition share (bar/pie), period-change leaders (top movers).

## Reuse (from usajobs_historical/web)

Vercel Python serverless + DuckDB over parquet (R2) + static front-end; `columns.py`
single-source registry; `parse_filters` WHERE-builder; shareable filter URLs; CSV export.

## What's new vs usajobs

Generic config-driven aggregate engine (a `dims.py` registry maps each dimension/metric key →
column + SQL + type + label source; allowlist-validated, no injection); two-dimension crosstab;
**two-period comparison with %Δ**; codebook labels; transaction/award toggle; viz variety;
table demoted to drill-down.

## API shape

`GET /api/table?dataset=contracts&level=transaction&rows=state&cols=fiscal_year`
`&metric=obligations&periodA=2024-02-01..2025-01-30&periodB=2025-02-01..2026-01-30&<filters>`
→ `{ rows: [...], cols: [...], cells: [[...]], totals, meta }`. Filters reuse the
`filter_<field>=a|b` / `_min` / `_max` convention. `GET /api/detail?...` = paginated drill-down rows.

## Acceptance test: reproduce the PLA DataDive from the UI

A user must be able to rebuild the PLA analysis with no custom code, purely via the builder
(this is the design's definition of done):
- Filter: funding sub-agency ∈ {10 land agencies}; periods A = Feb2024–Jan2025, B = Feb2025–Jan2026.
- Rows = agency / state / county / PSC (one at a time); Metric = obligations (A, B, %Δ) +
  distinct nonzero-net vendors.
- Western-states view = add a state filter. Top/bottom counties = sort by Δ.
- Copy the URL to return to any of these.

Trade-off accepted: the sector view groups by **raw PSC** (not Bernie's 11 custom buckets) —
flexibility over a baked-in taxonomy. A user-defined-grouping feature is a possible later add.
Numbers reproduce the *method* and approximate values, not his exact snapshot figures.
