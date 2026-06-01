"""Serving / transform layer: per-year compaction + award-summary derivation.

Runs after the backfill, reading the raw per-agency landing layer (local dir or
hf://) and producing the query-optimized serving layer:

  serve/{product}/fiscal_year=YYYY/part.parquet   transactions, one file/year, sorted
  awards/{product}/part.parquet                   one row per award (latest values + rollups)

Per-year compaction collapses ~4,520 tiny per-agency files into ~40 well-sized,
sorted files (agency stays a column) — far fewer file opens for cross-agency queries.

Award summary answers "how much did X get on this award" without the caller having
to dedupe modifications: for each award key, take the latest transaction's full row
(latest action_date, then last_modified_date) plus rollups summed across all its
transactions. This spans fiscal years, so it must read the whole product at once.
"""
from __future__ import annotations

import duckdb

AWARD_KEY = {
    "contracts": "contract_award_unique_key",
    "assistance": "assistance_award_unique_key",
}
# sort key per product for row-group pruning + compression
SORT_KEY = {"contracts": "recipient_name", "assistance": "recipient_name"}


def _reader(source_root: str, product: str, fy: str | None = None) -> str:
    """read_parquet(...) clause over the raw landing layer (local path or hf:// base)."""
    glob = f"{source_root}/{product}/" + (f"fiscal_year={fy}/**/*.parquet" if fy
                                          else "**/*.parquet")
    return f"read_parquet('{glob}', hive_partitioning=true, union_by_name=true)"


def compact_year(con: duckdb.DuckDBPyConnection, source_root: str, product: str,
                 fy: str, out_path: str) -> None:
    """All of one (product, year)'s per-agency files -> one sorted parquet."""
    con.execute(
        f"COPY (SELECT * FROM {_reader(source_root, product, fy)} "
        f"ORDER BY {SORT_KEY[product]}) "
        f"TO '{out_path}' (FORMAT parquet, COMPRESSION zstd)"
    )


def award_summary(con: duckdb.DuckDBPyConnection, source_root: str, product: str,
                  out_path: str) -> None:
    """One row per award: latest transaction's columns + obligation/count/date rollups."""
    key = AWARD_KEY[product]
    con.execute(f"""
        COPY (
          WITH ranked AS (
            SELECT *,
              row_number() OVER w AS _rn,
              sum(federal_action_obligation) OVER p   AS award_obligated_total,
              count(*) OVER p                          AS award_transaction_count,
              min(action_date) OVER p                  AS award_first_action_date,
              max(action_date) OVER p                  AS award_latest_action_date
            FROM {_reader(source_root, product)}
            WHERE {key} IS NOT NULL
            WINDOW p AS (PARTITION BY {key}),
                   w AS (PARTITION BY {key}
                         ORDER BY action_date DESC NULLS LAST,
                                  last_modified_date DESC NULLS LAST)
          )
          SELECT * EXCLUDE (_rn) FROM ranked WHERE _rn = 1
        ) TO '{out_path}' (FORMAT parquet, COMPRESSION zstd)
    """)
