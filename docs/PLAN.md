# Implementation plan

How to build the full thing: a HuggingFace dataset of the USAspending bulk files,
an R2 query mirror, a Vercel BI site, and a Colab demo notebook — following the
OPM (publish) and usajobs_historical (BI) precedents. Background, inventory, and
the data-tier decisions live in [`FINDINGS.md`](FINDINGS.md).

## Deliverables (one repo, four parts)

Single repo (`/repos/usaspending`), mirroring how OPM keeps pipeline + demo together
and usajobs_historical keeps the BI site in `web/`:

```
usaspending/
├── usaspending_archive/      # fetch → normalize → parquet → R2 + HF publish pipeline
├── web/                      # Vercel BI site (R2-backed, usajobs_historical-shaped)
├── demo.ipynb                # Colab demo (OPM-shaped)
├── metadata/                 # manifest.json (change detection)
├── docs/                     # FINDINGS.md, PLAN.md
└── .github/workflows/        # scheduled incremental refresh
```

## Core design decisions

These shape every phase; lock them before Phase 2.

1. **Two datasets, not one.** Contracts (297 cols) and Assistance (112 cols) have
   incompatible schemas → separate parquet trees.
2. **Partition layout (Hive):** `{contracts,assistance}/fiscal_year=YYYY/agency=CODE/part.parquet`.
   Lets DuckDB do predicate pushdown so the demo + BI site read only relevant files.
3. **Versioning via ETag + manifest, keep latest-only.** The archive re-publishes all
   files monthly under one new datestamp, but most old-FY files are byte-identical.
   The S3 listing exposes an **ETag (MD5) per key** — store it in `metadata/manifest.json`
   and only re-download + re-convert a (product, FY, agency) when its ETag changes.
   Keep only the latest snapshot in the partitioned tree (no per-month history) — the
   manifest records datestamp/ETag/rowcount so corrections are auditable without
   exploding storage. (OPM keeps every version because its files are tiny; we can't.)
4. **Typing:** publish amount columns as `double` and date columns as `date`, everything
   else as `varchar`. Faithful enough for republish, far better compression + query speed
   than all-string. Conversion via DuckDB `read_csv` → `COPY ... (FORMAT parquet, COMPRESSION zstd)`
   (memory-safe streaming — matters for big agency-FY files like DoD).
5. **R2 + HF both get the same parquet tree.** R2 = BI query backend (fast, private creds);
   HF = public distribution + demo source. Accepts storing data twice.
6. **BI uses a curated column subset** (`web/api/columns.py`) over the full 297/112; the
   parquet keeps all columns.

---

## Phase 0 — Scaffolding ✅ (done)

- `git init`, repo structure, `.gitignore`, `README.md`.
- `usaspending_archive/archive_index.py` — paginates + classifies the full archive.
- `docs/FINDINGS.md` — inventory, sizes, tiers.

## Phase 1 — One-agency end-to-end ✅ (validated 2026-05-30)

**Goal:** prove fetch → CSV → typed partitioned parquet for both products. De-risks schema before 91 GB.

Built + validated:
- `fetch.py` (`download_zip` ported from `scan.py`, retry/backoff/sentinels + `extract_csvs`).
- `convert.py` — DuckDB `read_csv(all_varchar)` → TRY_CAST amount/date cols → zstd parquet,
  written to `data/{product}/fiscal_year=YYYY/agency=CODE/*.parquet` (Hive).
- `schema.py` — name-pattern typing; verified: obligation/value/loan cols → DOUBLE,
  `*_date` → DATE, `*_fiscal_year` → VARCHAR (not date), rest → VARCHAR.
- `run_one_agency.py` — driver (download→convert→partition, with timing/size report).
- **Proof:** contracts 207×297 and assistance 453×112 → typed parquet; a typed aggregation
  over the partition glob (`sum(federal_action_obligation)`) returns a real DOUBLE — the
  demo/BI query path works on the published format.
- **Scale validated on Actions (097 DoD, 019 State):** CSV→parquet **≈8×** at real sizes →
  full corpus **~100 GB parquet**; conversion ~3 s/file. The throttle is the only bottleneck:
  an IP gets **~15–20 files** then is locked out. Corrected strategy (now in code): `download_zip`
  bails fast on `IP_BLOCKED` (2 short retries only) and the driver **stops the run** on a block
  so a fresh chained run continues — matches prod `scan.py`/`scan.yml:99`. Listing cached to
  `scratch/archive_index.json`.
- **Deliverable:** ✅ working pipeline, validated typed/partitioned output, real scale numbers.

## Phase 2 — Full backfill → R2 + HF (Contracts + Assistance Full)

**Goal:** the whole archive normalized and published once.

- `usaspending_archive/manifest.py` — port OPM's `manifest.py`; key = (product, FY, agency),
  value = {etag, datestamp, rowcount, hash, uploaded_at}. `sync_with_archive()` diffs live
  listing ETags vs manifest.
- `usaspending_archive/publish.py` — port OPM's `uploader.py`: batched `CommitOperationAdd`
  to HF (`create_repo(repo_type="dataset", exist_ok=True)`), retry/backoff; plus an R2
  uploader (reuse boto3 pattern from `pull_usaspending` / `usajobs_historical/web/api/data_loader.py`).
- Run the **first full backfill locally** (not GH Actions — too big for the 6 h cap):
  iterate all (product, FY, agency), download→convert→upload, write manifest as you go (resumable on ETag).
- **Decision needed:** HF org/repo id (OPM uses `impactproject/opm-ehri-data`).
- **Deliverable:** complete HF dataset + R2 mirror; manifest committed to repo.

## Phase 3 — Reference tables + dataset card (Tier 1) ✅ (2026-05-31)

**Goal:** make the dataset joinable + self-describing. Small, cheap, high leverage.

- `reference_data.py` — snapshots `data_dictionary` (457), `toptier_agencies` (111),
  `def_codes` (51), `glossary` (151), `assistance_listing` (56) to `data/reference/*.parquet`.
  These hit `api.usaspending.gov` (a different host than the throttled archive bucket — no lockout).
- `dataset_card.py` — generates the HF `README.md` (frontmatter + layout + reference-table
  counts read live + DuckDB quickstart + provenance/license). Counts stay honest.
- **Data-dictionary quirk handled + regression-tested:** 17 headers with repeated display
  names ('Element', 'Award File', … appear twice) + a constant trailing-null 18th column.
  `dd_columns`/`parse_data_dictionary` de-dupe by raw letter (e.g. `Element (N)`) and drop
  the null. 7/7 offline tests pass.
- **TODO (deferred, best-effort):** NAICS + PSC full code→description trees (recursive
  `references/filter_tree/...`).
- **Deliverable:** ✅ `reference/*` parquet + dataset card generated (upload deferred to M2 creds).

## Phase 4 — Backfill + incremental refresh (GitHub Actions) — built 2026-05-31

**Decided:** HF-only for now (R2 deferred to the website phase). HF dataset =
**`abigailhaddad/usaspending-bulk-awards`** (token `hf_syX`, created private — flip
public when backfill completes). HF publish path validated: card + 5 reference tables
live in the dataset.

Built:
- `backfill.py` — list → `manifest.changed()` → per file: download → convert → `HfApi.upload_file`
  at the stable partition key → `manifest.record` → save manifest (after every file → resumable).
  Stops on first `IP_BLOCKED`, prints `CHAIN_NEEDED`. Filters: `--agency`, `--product`, `--max-files`.
- `.github/workflows/refresh.yml` — runs backfill (HF_TOKEN secret set), commits the manifest,
  self-chains via `gh workflow run` (GITHUB_TOKEN, `actions: write`) while files remain;
  weekly Monday cron. Mirrors OPM's chain pattern.
- **Validated on Actions (agency 389):** run 1 processed 15 files then hit the throttle →
  `CHAIN_NEEDED` → run 2 resumed from the committed manifest, finished the last 5, stopped.
  Manifest-resumable, scope-preserving self-chain, idempotent. All 20 of 389's contract years
  live in HF.
- **TODO:** launch the full (unscoped) backfill — ~4,520 files ≈ many chained runs; flip
  dataset public when complete; add R2 mirror call in the website phase.

**Goal:** stay current automatically; never re-process unchanged files.

- `.github/workflows/refresh.yml` — weekly cron (+ manual dispatch). Steps:
  list archive → `manifest.changed()` → for each changed ETag:
  download→convert→upload→update manifest → commit manifest. **Stop on `IP_BLOCKED` and
  self-chain a fresh run** (`gh workflow run`) — validated: ~15–20 files/IP before lockout,
  so the first full backfill (~4,520 files) is **many chained runs**, made resumable by the
  manifest (each run drains the next slice of unprocessed/changed ETags). Pattern proven in
  prod `scan.yml:99`.
- Optionally also ingest the **Delta** files for faster incremental row-level updates
  (evaluate vs. just re-pulling changed Full files — Delta adds reconciliation complexity).
- Refresh reference tables on the same cron.
- **Deliverable:** hands-off weekly updates; manifest is the source of truth.

## Phase 4.5 — Serving / transform layer (runs after backfill) — building 2026-06-01

Built + validated (full runs execute post-backfill):
- `codebook.py` ✅ — parses the dictionary's Domain Values into a value→label table:
  **1,001 labels across 202 coded columns** (e.g. `extent_competed: A=FULL AND OPEN`,
  `C=NOT COMPETED`). Prose entries skipped. Offline tests cover the code/prose split.
- `transform.py` ✅ — `compact_year` (per-agency → one sorted file/year) and
  `award_summary` (windowed dedup: latest transaction's row + obligation/count/date rollups).
  Validated on a real slice: 252 txns → 170 awards (1 row/award), rollups correct
  (e.g. a 6-transaction award summed to $1.88M).
- TODO: run both across the full corpus after backfill; publish serving + awards trees;
  embed dictionary definitions as Parquet column metadata; dictionary-driven `schema.py` typing.

Original plan below.

The raw per-agency files (what the backfill produces) are great for ETag incremental
refresh but weak for queries: ~4,520 tiny files over hf://, transaction-level, 297 cols.
After backfill completes, add a transform pass producing the query-optimized serving layer.
User-value ranking (decided with user):

1. **Award-summary table** — derive one row per award (latest/aggregated values) from the
   transaction rows. The biggest usability unlock; what most analysts actually want.
2. **Per-year serving layer** — compact per-agency → ~40 per-year files (agency as a sorted
   column). ~100× fewer file opens for cross-agency/analytics queries; well-sized files.
   Sort rows within files (recipient / action_date) for row-group pruning — free, do always.
3. **Data-dictionary-driven metadata (force multiplier).** The snapshot has 457 documented
   columns, **289 coded fields** w/ value→label maps, **12 groupings**. Use it to:
   - emit a **codebook** reference table (value→label for the 289 coded columns);
   - embed each column's Definition as Parquet column metadata + a grouped column reference
     in the dataset card (self-documenting);
   - drive the BI site (group columns by the 12 groupings, hover-definitions, code decoding);
   - make `schema.py` typing dictionary-driven instead of name-heuristic.

Lower priority / subsumed: separate core+full column tiers (the award-summary table is
effectively the clean narrow table; dictionary groupings already enable column-picking).

Raw-layer fate (keep on HF vs serving-only): **decided after backfill.**

## Phase 5 — Vercel BI site (richer aggregation layer)

**Goal:** usajobs_historical-style filter/table UI, **but with a much deeper aggregation
layer** — USAspending's value is in slicing spend across many dimensions, not just a flat table.

Base (port from `usajobs_historical/web/`): Vercel Python serverless funcs querying R2
parquet via DuckDB; DataTables server-side pagination; shareable filter URLs; CSV export;
`static.json` for instant first paint; `web/api/columns.py` as the single source of truth
for the curated column subset (per product).

**What's different from usajobs — the aggregation layer:**
- `web/api/aggregate.py` becomes **multi-dimensional**, not the fixed 4 charts usajobs has.
  Support group-by on the dimensions the API exposes via `spending_by_category` (which we
  deliberately recompute in DuckDB instead of storing): **awarding/funding agency &
  sub-agency, recipient, recipient parent, NAICS, PSC, CFDA/program, federal account,
  state / county / congressional district, country, award type, DEFC**.
- A **pivot-style** endpoint: pick dimension(s) + measure (obligations / outlays / count)
  + a filter set → grouped totals. One generic DuckDB query builder over the partitioned
  tree drives all of them, so adding a dimension is a config line, not new code.
- **Spend-over-time** aggregation (by month/FY) as a first-class view.
- Geographic rollups (state/county/district) for a map view if we want one.
- All aggregations respect the active filter set + partition pruning (FY/agency) for speed.

Other adaptations:
- `data_loader.py` reads the **partitioned** Hive tree (glob + predicate pushdown) rather
  than usajobs's single parquet — partition pruning on FY/agency is the perf key at this scale.
- Product toggle (Contracts vs Assistance) since schemas differ.
- Tests: port `web/tests/{test_api,test_frontend}.py`; add aggregation-endpoint tests.
- **Decision needed:** Vercel project name (+ new-org R2 env vars).
- **Deliverable:** deployed BI site with a configurable multi-dimension aggregation layer.

## Phase 6 — Demo notebook

**Goal:** reproducible Colab analysis off the HF dataset.

- Port `opm/demo.ipynb`: `list_repo_files()` to discover partitions, DuckDB
  `read_parquet(..., hive_partitioning=true, union_by_name=true)`, example queries
  (top recipients, spend over time, agency drill-down), Plotly + CSV export, no auth.
- **Deliverable:** `demo.ipynb` with an "Open in Colab" badge in the README.

---

## Phase 7+ — Higher-effort data additions (post-v1, from FINDINGS Tier 2/3)

Each is a self-contained add-on once the v1 stack exists.

- **7. Subawards** — `bulk_download/awards/` with `sub_award_types`; async POST→poll→download,
  chunk by agency × FY. Reuse `usaspending_demo/fetch_reap_custom_bulk.py`'s poll loop.
  New `subawards/` parquet tree + manifest entries + BI product toggle.
- **8. Account File A/B/C** — `download/accounts/`; different grain (account-level). File C
  (account↔award bridge) is the prize. New `accounts/` trees; new BI views.
- **9. COVID-19 / IIJA view** — derived from File C's DEFC dimension; a curated filtered
  view + dashboard page once Phase 8 lands.

---

## Sequencing / milestones

| Milestone | Phases | Outcome |
|---|---|---|
| **M1 — Proof** | 0–1 | One agency end-to-end; real size/time numbers |
| **M2 — Data live** | 2–3 | Full Contracts+Assistance + reference tables on HF + R2, dataset card |
| **M3 — Self-updating** | 4 | Weekly auto-refresh via Actions |
| **M4 — Product** | 5–6 | Public BI site + demo notebook |
| **M5 — Depth** | 7–9 | Subawards, accounts, COVID/IIJA |

## Decisions (resolved 2026-05-30)

1. **Home** — lives in a repo under **another org** (not personal). HF dataset + GitHub
   repo under that org. _Exact org + repo/dataset names still TBD — needed before M2 publish,
   not before M1._
2. **R2** — a **new bucket under the other org's** R2 account (fresh, not a reused prefix).
   _Creds/bucket name needed before M2._
3. **BI site** — usajobs_historical-style, **but with a richer aggregation layer** (see Phase 5).
4. **Delta files** — undecided → default to **simple: re-pull changed Full files** (ETag-gated)
   in Phase 4; revisit Delta only if refresh latency becomes a problem.
5. **Per-month history** — **latest-only confirmed**; manifest keeps the audit trail.

Still needed before each milestone: org + HF/GitHub names and R2 bucket/creds (M2);
Vercel project name (M4). None block M1.
