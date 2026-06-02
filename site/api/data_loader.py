"""DuckDB connection + the parquet source expression for the table builder.

Source is configurable so the same engine runs against local files (dev), the public
HuggingFace dataset, or R2 (the planned production backend — no egress fees):

  USP_SOURCE_TMPL  a read_* expression with a {dataset} placeholder, e.g.
                   "read_csv('/path/{dataset}/*.csv', all_varchar=true)"  (local dev)
  (unset)          -> the public HF dataset via hf:// (CREATE SECRET hf if HF_TOKEN set)

When CF_R2_* is present we point DuckDB at R2 (s3-compatible) instead.
"""
import os
import duckdb

import query  # for hf_source

# The data is static between monthly refreshes, so identical query responses are safe to
# cache hard. Browser 1h, CDN (Vercel edge) 1 day, serve-stale-while-revalidating a week.
# Repeat/identical queries are then served from the edge and never re-hit the parquet —
# which is what keeps the backend off HuggingFace's rate limiter. Only 200s carry this;
# error responses must stay uncached so a transient 429 doesn't get pinned for a day.
CACHE_CONTROL = "public, max-age=3600, s-maxage=86400, stale-while-revalidate=604800"


def source_expr(dataset):
    tmpl = os.environ.get("USP_SOURCE_TMPL")
    if tmpl:
        return tmpl.format(dataset=dataset)
    if os.environ.get("CF_R2_BUCKET"):
        bucket = os.environ["CF_R2_BUCKET"]
        return (f"read_parquet('s3://{bucket}/{dataset}/**/*.parquet', "
                f"hive_partitioning=true, union_by_name=true)")
    return query.hf_source(dataset)


def get_conn():
    con = duckdb.connect()
    con.execute("INSTALL httpfs; LOAD httpfs;")
    if os.environ.get("CF_R2_ACCOUNT_ID"):
        con.execute(f"""
            CREATE SECRET r2 (TYPE r2, KEY_ID '{os.environ['CF_R2_ACCESS_KEY_ID']}',
              SECRET '{os.environ['CF_R2_SECRET_ACCESS_KEY']}',
              ACCOUNT_ID '{os.environ['CF_R2_ACCOUNT_ID']}')
        """)
    elif os.environ.get("HF_TOKEN"):
        con.execute(f"CREATE SECRET hf (TYPE huggingface, TOKEN '{os.environ['HF_TOKEN']}')")
    return con
