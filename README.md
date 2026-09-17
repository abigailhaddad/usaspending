# usaspending

A pipeline that mirrors the public [USAspending Award Data Archive](https://files.usaspending.gov/award_data_archive/)
(prime contract & financial-assistance bulk files) into clean, typed, partitioned
Parquet, and publishes it as a Hugging Face dataset:

**[huggingface.co/datasets/abigailhaddad/usaspending-bulk-awards](https://huggingface.co/datasets/abigailhaddad/usaspending-bulk-awards)**

The archive itself is ~4,600 per-agency ZIP/CSV files with no easy way to query
across agencies or years. This turns it into typed, zstd-compressed Parquet,
queryable directly over the network with DuckDB — no download required. The
dataset card there (auto-generated from the current snapshot, see
`usaspending_archive/dataset_card.py`) is the source of truth for row counts,
sizes, and column layout; this README won't repeat numbers that go stale.

Two layers ship in the dataset — use `serve/`, not the per-agency raw files, for
remote queries (see below).

## Quick start

```python
import duckdb
con = duckdb.connect()
con.execute("INSTALL httpfs; LOAD httpfs;")
con.sql('''
  SELECT recipient_name, sum(federal_action_obligation) AS obligated
  FROM read_parquet(
    'hf://datasets/abigailhaddad/usaspending-bulk-awards/serve/contracts/2024.parquet'
  )
  WHERE awarding_agency_code = '097'
  GROUP BY 1 ORDER BY 2 DESC LIMIT 10
''').show()
```

`demo.ipynb` is a runnable Colab notebook version of this.

**Use `serve/{product}/{fiscal_year}.parquet`, not the raw
`{product}/fiscal_year=YYYY/agency=CODE/` tree, for queries like this.** The raw
tree is one file per (product, FY, agency) — thousands of files — and globbing
it with `hive_partitioning=true` over `hf://` makes DuckDB recursively list every
partition directory, which is slow and gets rate-limited by Hugging Face (verified:
the raw-tree glob above didn't finish in 90s; the `serve/` query above takes ~10s).
`serve/` has one compacted file per (product, fiscal year) with all agencies
inside — filter on `awarding_agency_code` / `funding_agency_code` (the per-row
values) rather than `agency` (a leftover literal column, always `"All"`, in that
layer). See [`compact_serve.py`](usaspending_archive/compact_serve.py) for why.

## How it stays current

The archive republishes monthly; this repo checks daily and only re-processes
files whose ETag changed (tracked in `metadata/manifest.json`), all via scheduled
GitHub Actions — nothing needs to be run by hand:

| Workflow | Runs | Does | Script |
|---|---|---|---|
| [`refresh.yml`](.github/workflows/refresh.yml) | daily | Diffs the archive against the manifest, converts + uploads changed files to HF, self-chains until drained (the source CDN throttles a runner IP after ~15–20 files) | [`backfill.py`](usaspending_archive/backfill.py) (publishes via [`publish.py`](usaspending_archive/publish.py)) |
| [`rebuild.yml`](.github/workflows/rebuild.yml) | after a drain with changes | Compacts per-agency raw files into a per-year "serve" layer on HF, mirrors it to R2, regenerates precomputed dashboard aggregates | [`compact_serve.py`](usaspending_archive/compact_serve.py) → [`precompute.py`](usaspending_archive/precompute.py) |
| [`refresh_reference.yml`](.github/workflows/refresh_reference.yml) | manual | Re-snapshots the small reference/dimension tables (data dictionary, agency crosswalk, etc.) and publishes them to HF | [`reference_data.py`](usaspending_archive/reference_data.py) |
| [`test.yml`](.github/workflows/test.yml) | every push/PR | Offline pytest suite, no network or credentials | — |
| [`validate.yml`](.github/workflows/validate.yml) | manual | Runs the fetch→convert pipeline for one agency to sanity-check timing/size | [`run_one_agency.py`](usaspending_archive/run_one_agency.py) |

`backfill.py` is the one doing the actual HF writes on the daily schedule — it's
the script to read first if you want to understand how data lands on Hugging Face.

For current file counts, sizes, and FY range of the source archive, run
`python3 -m usaspending_archive.archive_index` — those numbers change as the
archive grows, so this README doesn't state them.

## Repo layout

```
usaspending_archive/   # the pipeline: fetch archive zips → typed Parquet → HF publish
  fetch.py                download + extract one agency/FY zip
  convert.py               CSV → typed, partitioned Parquet (DuckDB)
  schema.py                column typing rules
  manifest.py              ETag-based change tracking (metadata/manifest.json)
  backfill.py              drives fetch→convert→publish across changed files — the
                            script that actually writes to HF on the daily schedule
  publish.py               HF (+ R2) upload helpers, used by backfill.py
  compact_serve.py         per-agency raw → per-year "serve" layer (query-optimized),
                            uploaded to HF directly
  plan_compact.py          decides which (product, year) shards rebuild.yml compacts
  precompute.py            builds the dashboard JSON in site/public/precomputed
  reference_data.py        snapshots small dimension tables (agency codes, CFDA, etc.)
                            and publishes them to HF
  codebook.py              parses the data dictionary's coded-value → label maps
  transform.py             award-summary rollups (transaction rows → one row/award)
  dataset_card.py          generates data/reference/DATASET_CARD.md (the HF README)
  archive_index.py         lists/classifies the live source archive

data/reference/         # reference-table Parquet + the generated dataset card
metadata/manifest.json  # (product, FY, agency) → etag/rowcount/upload time — the
                         # change-detection source of truth; also the resumability
                         # mechanism for chained backfill runs
tests/                  # offline pytest suite (pipeline helpers + BI query engine)
docs/                   # design docs — see note below
site/                   # Next.js BI viewer (DuckDB-over-R2). Experimental / not
                         # the deliverable — the dataset on HF is
demo.ipynb              # Colab notebook: query the HF dataset with DuckDB
```

[`docs/BI_DESIGN.md`](docs/BI_DESIGN.md) documents the experimental `site/`
viewer — a design doc, not a description of what's live.

## Local development

```bash
pip install -r requirements-dev.txt
python -m pytest tests/ -q
```

The test suite is offline (fixtures in `tests/fixtures/`) — no HF token or
network access needed. To run a real pipeline step locally (e.g. to test a
change to `convert.py` or `manifest.py`) you'll need an `HF_TOKEN` with write
access to the dataset; the workflows above show the exact invocations
(`python -m usaspending_archive.backfill --agency <code> --max-files N` is the
cheapest way to exercise the full path end to end against one agency).

## What's *not* in this dataset

Only what's in the archive's ZIP files: prime contracts + assistance ("Full",
plus "Delta" for incremental changes). Subawards and account-level data
(File A/B/C) aren't published in the static archive at all — they'd require
USAspending's Custom Bulk Download API, which this pipeline doesn't call.
