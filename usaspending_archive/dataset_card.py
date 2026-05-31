"""Generate the HuggingFace dataset card (README.md for the HF repo).

Built from the live snapshot so counts stay honest: reference-table row counts are
read from data/reference/*.parquet. Product column counts + the archive inventory
are documented constants (validated 2026-05-31; see docs/FINDINGS.md).

    python -m usaspending_archive.dataset_card   # writes data/reference/DATASET_CARD.md
"""
from __future__ import annotations

from pathlib import Path

import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parent.parent
REF = ROOT / "data" / "reference"

# Documented constants (docs/FINDINGS.md)
CONTRACTS_COLS = 297
ASSISTANCE_COLS = 112
FY_RANGE = "FY2007–present"

REF_TABLES = {
    "data_dictionary": "Rosetta crosswalk — every column's definition, domain values, and source file",
    "toptier_agencies": "Agency code ↔ name crosswalk",
    "def_codes": "Disaster Emergency Fund Codes (COVID-19 = L–U, IIJA = Z & 1)",
    "glossary": "Plain-language term definitions",
    "assistance_listing": "CFDA / assistance program catalog",
}


def _rows(name: str) -> int | None:
    p = REF / f"{name}.parquet"
    return pq.read_metadata(p).num_rows if p.exists() else None


def generate() -> str:
    ref_lines = []
    for name, desc in REF_TABLES.items():
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

The source publishes ~4,600 per-agency ZIP/CSV files (~830 GB uncompressed). This
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
```

## Reference tables

| File | Rows | Description |
|---|---|---|
{ref_block}

The data dictionary documents every column in both products.

## Quick start (DuckDB)

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
```

## Provenance & updates

- **Source:** USAspending.gov Award Data Archive (U.S. Government public-domain data).
- **Coverage:** {FY_RANGE}, prime awards only. Subawards and account File A/B/C are not
  in the source archive (they come from USAspending's Custom Bulk Download API).
- **Updates:** refreshed when the source re-publishes; only changed (agency, FY) slices
  are re-processed (tracked by file ETag). Latest snapshot only.
- **Not** the full USAspending Postgres database dump.
"""


if __name__ == "__main__":
    out = REF / "DATASET_CARD.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(generate())
    print(f"wrote {out.relative_to(ROOT)} ({out.stat().st_size} bytes)")
