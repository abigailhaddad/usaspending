"""Generate the HuggingFace dataset card (README.md for the HF repo).

Built from the live snapshot so counts stay honest: reference-table row counts are
read from data/reference/*.parquet. Product column counts + the archive inventory
are documented constants (validated 2026-05-31).

    python -m usaspending_archive.dataset_card   # writes data/reference/DATASET_CARD.md
"""
from __future__ import annotations

from pathlib import Path

import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parent.parent
REF = ROOT / "data" / "reference"

# Documented constants (verified against the source archive's column headers)
CONTRACTS_COLS = 297
ASSISTANCE_COLS = 112
FY_RANGE = "FY2007–present"

REF_TABLES = {
    "data_dictionary": "Rosetta crosswalk — column definitions, domain values, and source file",
    "toptier_agencies": "Agency code ↔ name crosswalk (toptier agencies only)",
    "agency_codes": "CGAC agency code ↔ name for every agency code in the archive",
    "def_codes": "Disaster Emergency Fund Codes; the `disaster` column tags COVID-19 and IIJA codes",
    "glossary": "Plain-language term definitions",
    "assistance_listing": "Assistance Listing (CFDA) 2-digit agency prefixes, with the number of programs under each (no program titles)",
}


def _rows(name: str) -> int | None:
    p = REF / f"{name}.parquet"
    return pq.read_metadata(p).num_rows if p.exists() else None


def _disaster_codes() -> str | None:
    """'COVID-19 = L, M, ...; IIJA = 1, Z' read from def_codes.parquet's `disaster`
    column, so the card can't drift from the table (it once said 'L–U', which
    included non-COVID codes Q–T and left out V)."""
    p = REF / "def_codes.parquet"
    if not p.exists():
        return None
    t = pq.read_table(p, columns=["code", "disaster"]).to_pylist()
    labels = {"covid_19": "COVID-19", "infrastructure": "IIJA"}
    parts = []
    for key, label in labels.items():
        codes = sorted(r["code"] for r in t if r["disaster"] == key)
        if codes:
            parts.append(f"{label} = {', '.join(codes)}")
    return "; ".join(parts) or None


def generate() -> str:
    ref_lines = []
    for name, desc in REF_TABLES.items():
        if name == "def_codes" and (dc := _disaster_codes()):
            desc = f"Disaster Emergency Fund Codes ({dc}, per the `disaster` column)"
        n = _rows(name)
        cnt = f"{n:,} rows" if n is not None else "—"
        ref_lines.append(f"| `reference/{name}.parquet` | {cnt} | {desc} |")
    ref_block = "\n".join(ref_lines)

    return f"""---
license: other
license_name: us-government-works
pretty_name: USAspending bulk awards (contracts & assistance)
language:
  - en
tags:
  - government
  - federal-spending
  - contracts
  - grants
  - usaspending
size_categories:
  - 100M<n<1B
---

# USAspending bulk awards — contracts & assistance

Clean, partitioned, query-ready Parquet mirror of the public
[USAspending Award Data Archive](https://files.usaspending.gov/award_data_archive/)
(prime contract and financial-assistance transactions, {FY_RANGE}, all agencies).

The source publishes ~4,700 ZIP/CSV files (one per product × fiscal year × agency, plus an all-agency file per product × year) (~830 GB uncompressed). This
dataset normalizes them to typed, zstd-compressed Parquet (~8× smaller) with
amount columns as `double` and date columns as `date`, partitioned for fast
predicate-pushdown querying.

## Layout

Two datasets (the schemas differ — contracts {CONTRACTS_COLS} columns, assistance
{ASSISTANCE_COLS} columns), Hive-partitioned by fiscal year and agency:

```
contracts/fiscal_year=YYYY/agency=CODE/part.parquet     # prime contracts ({CONTRACTS_COLS} cols)
assistance/fiscal_year=YYYY/agency=CODE/part.parquet    # grants/loans/etc. ({ASSISTANCE_COLS} cols)
reference/*.parquet                                     # joinable dimension tables (below)
serve/{{contracts,assistance}}/YYYY.parquet               # one compacted file per product × year (no duplicates)
```

> **Warning: `agency=All` is a duplicate — never combine it with the other agency partitions.**
> Each `fiscal_year=YYYY/` directory holds the per-agency partitions (`agency=097`,
> `agency=075`, …) **and** an `agency=All` partition, which is USAspending's own
> complete per-year archive file: a full second copy of every transaction in that
> year's per-agency partitions. A glob such as `contracts/**/*.parquet`, or any query
> over a fiscal year without an agency filter, therefore counts every transaction
> **twice** (row counts and dollar totals come out exactly 2×). In the raw tree,
> always do one of:
>
> - filter `agency != 'All'` (per-agency detail), **or**
> - use only `agency = 'All'` (one complete copy per year), **or**
> - filter to specific agencies (`agency = '097'`).
>
> For remote queries, prefer the `serve/` layer below. It's built from the `All`
> file alone, so each transaction appears once.

## Reference tables

| File | Rows | Description |
|---|---|---|
{ref_block}

The data dictionary covers most columns in both products. A few archive columns
have no entry in it: `recipient_duns`, `recipient_parent_duns`, `initial_report_date`,
the four `prime_award_transaction_*_cd_original` / `_cd_current` congressional-district
columns, and (assistance only) `generated_pragmatic_obligations`.

## Quick start (DuckDB)

### Querying without downloading (recommended)

The `serve/{{product}}/{{fiscal_year}}.parquet` files are one compacted file per
product per fiscal year (all agencies), sized for remote streaming — this is
the fastest way to query without cloning the repo. Filter on
`awarding_agency_code` / `funding_agency_code` for agency (the `agency` column
in this layer is a leftover literal `"All"`, not a per-row value):

```python
import duckdb
con = duckdb.connect()
con.execute("INSTALL httpfs; LOAD httpfs;")
con.sql('''
  SELECT recipient_name, sum(federal_action_obligation) AS obligated
  FROM read_parquet('hf://datasets/abigailhaddad/usaspending-bulk-awards/serve/contracts/2024.parquet')
  WHERE awarding_agency_code = '097'
  GROUP BY 1 ORDER BY 2 DESC LIMIT 10
''').show()
```

### After cloning / downloading the dataset locally

The raw layer (one file per product × fiscal year × agency, Hive-partitioned)
has full per-transaction detail. Once it's on disk, `hive_partitioning=true`
gives partition pruning for free:

```python
import duckdb
con = duckdb.connect()
# Top recipients of FY2024 contracts at one agency — partition pruning reads only that slice
con.sql('''
  SELECT recipient_name, sum(federal_action_obligation) AS obligated
  FROM read_parquet('contracts/**/*.parquet', hive_partitioning=true)
  WHERE fiscal_year = '2024' AND agency = '097'
  GROUP BY 1 ORDER BY 2 DESC LIMIT 10
''').show()

# Government-wide totals from the raw tree: EXCLUDE agency=All, or every row counts twice
con.sql('''
  SELECT fiscal_year, count(*) AS transactions, sum(federal_action_obligation) AS obligated
  FROM read_parquet('contracts/**/*.parquet', hive_partitioning=true)
  WHERE agency != 'All'
  GROUP BY 1 ORDER BY 1
''').show()
```

Don't run that same `hive_partitioning=true` glob directly over `hf://` without
downloading first — it makes DuckDB recursively list every partition directory
over the network, which is slow and gets rate-limited by Hugging Face at this
file count. Use the `serve/` layer above for remote queries instead.

## Provenance & updates

- **Source:** USAspending.gov Award Data Archive (U.S. Government public-domain data).
- **Coverage:** {FY_RANGE}, prime awards only. Subawards and account File A/B/C are not
  in the source archive (they come from USAspending's Custom Bulk Download API).
- **Updates:** a daily job checks the source archive, which re-publishes about monthly.
  It re-processes changed (agency, FY) slices, tracked by file ETag, but only for the
  current and prior fiscal year. Older fiscal years are re-ingested only by a manual
  full run, so they can come from an earlier monthly cycle than the recent years.
  One copy of each slice is kept; there is no version history.
- **Not** the full USAspending Postgres database dump.
"""


if __name__ == "__main__":
    out = REF / "DATASET_CARD.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(generate())
    print(f"wrote {out.relative_to(ROOT)} ({out.stat().st_size} bytes)")
