"""Precompute a ZIP-level spending summary so the public can filter/download by ZIP
without aggregating 2 billion rows in real time.

Grain: dataset × fiscal_year × recipient ZIP5. Columns:
    dataset, fiscal_year, recipient_zip, recipient_state_code, obligations, transactions

One scan per dataset over the serve parquet; written as a single parquet via DuckDB COPY.
Run from the repo root with CF_R2_* + CF_R2_PREFIX set:
    python usaspending_archive/build_zip_summary.py
Output: aggregates/zip_summary.parquet (then published to HF by publish step).
"""
import os
from pathlib import Path

import duckdb

OBL = "TRY_CAST(federal_action_obligation AS DOUBLE)"
HF_REPO = "abigailhaddad/usaspending-bulk-awards"

# ZIP5 source column differs by dataset (see serve schema); strip to 5, drop empties.
ZIP = {
    "contracts": "NULLIF(substr(recipient_zip_4_code, 1, 5), '')",
    "assistance": "NULLIF(substr(recipient_zip_code, 1, 5), '')",
}


def source(dataset):
    bucket = os.environ.get("CF_R2_BUCKET")
    if bucket:
        prefix = os.environ.get("CF_R2_PREFIX", "")
        return f"read_parquet('r2://{bucket}/{prefix}serve/{dataset}/*.parquet', union_by_name=true)"
    return f"read_parquet('hf://datasets/{HF_REPO}/serve/{dataset}/*.parquet', union_by_name=true)"


def connect():
    con = duckdb.connect()
    if os.path.isdir("/tmp"):
        con.execute("SET home_directory='/tmp'")
    con.execute("INSTALL httpfs; LOAD httpfs;")
    if os.environ.get("CF_R2_ACCOUNT_ID"):
        con.execute(f"""CREATE SECRET r2 (TYPE r2, KEY_ID '{os.environ['CF_R2_ACCESS_KEY_ID']}',
            SECRET '{os.environ['CF_R2_SECRET_ACCESS_KEY']}', ACCOUNT_ID '{os.environ['CF_R2_ACCOUNT_ID']}')""")
    elif os.environ.get("HF_TOKEN"):
        con.execute(f"CREATE SECRET hf (TYPE huggingface, TOKEN '{os.environ['HF_TOKEN']}')")
    return con


def query(dataset):
    z = ZIP[dataset]
    return (
        f"SELECT '{dataset}' AS dataset, action_date_fiscal_year AS fiscal_year, "
        f"  {z} AS recipient_zip, any_value(recipient_state_code) AS recipient_state_code, "
        f"  sum({OBL}) AS obligations, count(*) AS transactions "
        f"FROM {source(dataset)} "
        f"WHERE {z} IS NOT NULL AND action_date_fiscal_year IS NOT NULL "
        f"GROUP BY 1, 2, 3")


def main():
    con = connect()
    dest = Path("aggregates")
    dest.mkdir(exist_ok=True)
    out = dest / "zip_summary.parquet"
    sql = " UNION ALL ".join(query(d) for d in ("contracts", "assistance"))
    con.execute(f"COPY ({sql} ORDER BY dataset, fiscal_year, recipient_zip) "
                f"TO '{out}' (FORMAT PARQUET, COMPRESSION ZSTD)")
    n, z, mb = con.execute(
        f"SELECT count(*), count(DISTINCT recipient_zip), "
        f"(SELECT sum(obligations) FROM read_parquet('{out}')) FROM read_parquet('{out}')").fetchone()
    print(f"wrote {out} ({out.stat().st_size/1e6:.2f} MB): {n:,} rows, {z:,} distinct ZIPs, "
          f"${mb/1e12:.1f}T total", flush=True)


if __name__ == "__main__":
    main()
