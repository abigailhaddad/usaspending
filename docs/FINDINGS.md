# USAspending bulk-archive republish — scoping & feasibility findings

_Captured 2026-05-30. Empirical, not guesses — measured against the live archive._

## Goal

Mirror the OPM project's pattern for USAspending's public bulk files:
1. **HF dataset** — normalize the per-agency/year archive zips to partitioned parquet, publish to HuggingFace.
2. **R2 + HF mirror** — R2 is the query backend for the BI site; HF is the public-distribution copy + demo source.
3. **Vercel BI site** — usajobs_historical-shaped (DuckDB over partitioned parquet, DataTables + Chart.js, shareable filter URLs).
4. **Demo notebook** — OPM-shaped Colab notebook that auto-discovers HF files and queries with DuckDB.

Value-add is **format + queryability + BI**, not access — the archive is already public domain.

## The Award Data Archive — complete inventory

Source: `https://files.usaspending.gov/award_data_archive/` (S3 bucket `dti-usaspending-monthly-downloads`).
Full listing paginated 2026-05-30 — **4,629 keys, 91.4 GB compressed, FY2007–FY2026, one file per agency**.

| Product | Files | Compressed | Grain |
|---|---|---|---|
| Contracts_Full (prime contracts) | 2,260 | 54.8 GB | per agency × FY |
| Assistance_Full (grants/loans/etc.) | 2,260 | 35.8 GB | per agency × FY |
| Contracts_Delta (monthly changes) | 68 | 0.4 GB | FY(All) × agency |
| Assistance_Delta | 41 | 0.5 GB | FY(All) × agency |

**There are ZERO subaward / account / File B/C files in this archive** — confirmed across all 4,629 keys.
"Everything in the zips" = **Contracts + Assistance, Full (± Delta)**.

## Measured expansion (sample: FY2024 agency 389 contracts, agency 309 assistance)

- zip → CSV ≈ **9.3×** → **~830 GB uncompressed CSV** for the full corpus.
- CSV → parquet(zstd) on tiny samples only ~2–4× (too small to compress well); on full-size files expect far better. **Budget published parquet at ~90–150 GB.**
- **Contracts = 297 columns. Assistance = 112 columns.** Different schemas — two separate tables, not one.

## Other USAspending data NOT in the archive — available without the Postgres dump

The only non-Postgres mechanism for these is the **Custom Bulk Download API** (async: POST → poll `status_url` → download generated zip). `usaspending_demo/fetch_reap_custom_bulk.py` already implements this pattern.

- `POST /api/v2/bulk_download/awards/` — supports `prime_award_types` **and `sub_award_types`** → this is how you get **subawards**. Filter by agency + date range + award type.
- `POST /api/v2/bulk_download/accounts/` — **File A** (account balances), **File B** (account breakdown by program activity / object class), **File C** (account breakdown by award) → the account/financial data.

Caveats vs. the static archive: async + rate-limited + per-request row/size caps (must chunk by agency × year × award type), slower, more fragile. Fine for targeted slices; heavy for "everything."

## What else is worth getting (full API review, 2026-05-30)

Reviewed the full `api.usaspending.gov/docs/endpoints` surface. The vast majority of
endpoints are either (a) **aggregations** (`spending_by_category`, `spending_over_time`,
`disaster/*`, `agency/<code>/*` breakdowns) we can recompute ourselves in DuckDB from
the bulk tables, or (b) **single-record lookups** (`awards/<id>`, `recipient/<hash>`,
`idvs/*`) that aren't bulk-republishable. Don't republish those.

The genuinely additive **bulk datasets** not in the static archive, tiered by value/effort:

### Tier 1 — grab now (tiny, cheap, makes everything else joinable + self-describing)
Snapshot these reference tables to parquet; they're small JSON and rarely change:
- `references/data_dictionary/` — the Rosetta crosswalk / column definitions. **Essential** for the HF dataset card + BI column labels.
- `bulk_download/list_agencies/` + `references/toptier_agencies/` — agency code crosswalk (scan.py already grabs `agency_codes.csv`).
- `references/assistance_listing/` + `cfda/totals/` — CFDA / program catalog (labels assistance rows).
- `references/naics/` + `filter_tree/psc/` — NAICS (industry) & PSC (product/service) code trees (label contract rows).
- `references/def_codes/` — Disaster Emergency Fund Codes (COVID = L–U, IIJA = Z & 1). Needed to interpret DEFC columns.
- `references/glossary/` — definitions for the methodology/about page.

### Tier 2 — high analytical value, real work (phase 2)
- **Subawards** — `bulk_download/awards/` with `sub_award_types`. Who primes pass money down to. Async API, chunk by agency × year. (Working reference: `usaspending_demo/fetch_reap_custom_bulk.py`.)
- **Account File A / B / C** — `download/accounts/` (or `bulk_download/accounts/`). The budgetary/financial layer, a *different grain* than awards:
  - File A = account balances; File B = account breakdown by program activity / object class; **File C = account breakdown by award** — the bridge that traces appropriations → awards. File C is the unique-value one.

### Tier 3 — curated high-interest view, derivable
- **COVID-19 / IIJA tagged spending** — not a separate dataset; it's the DEFC dimension on File C (+ `download/disaster/` bundles account+award for disaster funding). High public interest; build as a filtered view once File C is in.

### Confirmed dead-ends / no-ops
- `bulk_download/list_monthly_files/` just points back to the static archive we already enumerate — nothing new.
- All `spending_by_category` / `spending_over_time` / `agency/<code>/*` / `disaster/*` aggregations → recompute in DuckDB, don't store.

## Reuse map (how much code already exists)

| Component | Source repo | Reuse |
|---|---|---|
| Download archive zips, datestamp autodetect, agency-code fetch, resumability | `pull_usaspending/pull_usaspending/scan.py` | ~90% (strip sole-source filter; keep all rows; add Assistance + Delta) |
| HF publish: batched commits, retry, manifest change-detection, versioned filenames, GH Actions run-chaining | `opm/opm_pipeline/{uploader,manifest}.py`, `run_daily.py` | ~80% |
| CSV→parquet (zstd) | `opm/opm_pipeline/converter.py` | mostly |
| Vercel BI: DuckDB-over-parquet serverless, DataTables server-side pagination, Chart.js aggs, single-source-of-truth `columns.py`, shareable filter URLs, R2 fallback loader | `usajobs_historical/web/` | ~70% (swap columns + partitioned-parquet source) |
| Demo notebook (Colab, auto-discover HF, DuckDB union_by_name, Plotly) | `opm/demo.ipynb` | ~85% |
| Custom Bulk Download API (subawards / accounts) | `usaspending_demo/fetch_reap_custom_bulk.py` | working reference |

## Open issues / decisions

1. **Scale** is the dominant risk (OPM's biggest file ~30 MB/mo; this is ~830 GB CSV). MUST partition (Hive `fiscal_year=/agency=`) for DuckDB pushdown; the demo + Vercel layer cannot load it all.
2. **Versioning**: archive re-publishes Full files monthly w/ new datestamp; old FYs get retroactively corrected. Keep every snapshot (storage explodes) or latest-per-FY (lose correction history)? OPM keeps versions because its files are tiny — can't do that blindly here.
3. **Schema drift** across FY2007→2026; demo uses `union_by_name=True`, but BI `columns.py` needs a stable common subset.
4. **GH Actions 6h cap**: first full backfill is huge — likely a one-time local push, then incremental via Actions.
5. **Stores data twice** (R2 query backend + HF mirror) — accepted per "R2 + HF mirror" decision.

## Decisions locked

- Scope: **everything in the zips** (Contracts + Assistance Full, ± Delta); NOT the Postgres dump. Evaluate adding subawards/accounts via the Custom Bulk Download API as a phase 2.
- Query backend: **R2 + HF mirror**.
- Repo home: **this repo** (`/repos/usaspending`).
