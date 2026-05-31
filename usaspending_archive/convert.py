"""CSV -> typed, partitioned Parquet via DuckDB.

DuckDB streams the CSV (memory-safe for big agency-years), casts recognized
amount/date columns (see schema.py), and writes one Parquet file per archive
zip into a Hive-partitioned tree:

    {root}/{product}/fiscal_year=YYYY/agency=CODE/{stem}.parquet

If a zip split into multiple CSVs, they're unioned by name into one partition file.
"""
from __future__ import annotations

from pathlib import Path

import duckdb

from . import schema


def _read_clause(csv_paths: list[Path]) -> str:
    files = "[" + ", ".join("'" + str(p).replace("'", "''") + "'" for p in csv_paths) + "]"
    # all_varchar: no type sniffing; union_by_name: tolerate column drift across split files.
    return (f"read_csv({files}, all_varchar=true, header=true, "
            f"union_by_name=true, sample_size=-1)")


def csv_to_parquet(
    csv_paths: list[Path],
    out_path: Path,
    con: duckdb.DuckDBPyConnection | None = None,
) -> dict:
    """Convert CSV(s) -> one typed zstd Parquet file. Returns {rows, cols, bytes}."""
    con = con or duckdb.connect()
    read = _read_clause(csv_paths)

    cols = [row[0] for row in con.execute(f"DESCRIBE SELECT * FROM {read}").fetchall()]
    select = ", ".join(schema.select_expr(c) for c in cols)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    con.execute(
        f"COPY (SELECT {select} FROM {read}) TO '{out_path}' "
        f"(FORMAT parquet, COMPRESSION zstd)"
    )
    rows = con.execute(f"SELECT count(*) FROM read_parquet('{out_path}')").fetchone()[0]
    return {"rows": rows, "cols": len(cols), "bytes": out_path.stat().st_size}


def partition_path(root: Path, product: str, fiscal_year: str, agency: str, stem: str) -> Path:
    return root / product / f"fiscal_year={fiscal_year}" / f"agency={agency}" / f"{stem}.parquet"
