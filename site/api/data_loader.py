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
        prefix = os.environ.get("CF_R2_PREFIX", "")  # e.g. "bulk-awards/" to namespace a shared bucket
        # The serving layer on R2: one parquet per fiscal year (mirrors hf_source's layout),
        # so reads are a single low-latency dir listing — fast cold, no HuggingFace throttling.
        # NB: use the r2:// scheme (not s3://) so DuckDB's `TYPE r2` secret routes to the
        # Cloudflare endpoint; s3:// would resolve to AWS and 403.
        return (f"read_parquet('r2://{bucket}/{prefix}serve/{dataset}/*.parquet', "
                f"union_by_name=true)")
    return query.hf_source(dataset)


_REMOTE_SCHEMES = ("hf://", "r2://", "s3://", "http://", "https://")


def _needs_httpfs(source):
    """Whether this source is remote and so needs the httpfs extension + creds.
    A local file source (USP_SOURCE_TMPL pointing at read_csv/parquet of a path) does
    not — and on a cold runner `INSTALL httpfs` would require network, so skip it.
    `source` is the resolved source_expr(); None means fall back to env detection."""
    if source is not None:
        return any(s in source for s in _REMOTE_SCHEMES)
    tmpl = os.environ.get("USP_SOURCE_TMPL")
    if tmpl:
        return any(s in tmpl for s in _REMOTE_SCHEMES)
    return True  # default = public HF source, or R2 via CF_R2_*


def get_conn(source=None):
    con = duckdb.connect()
    # On Vercel only /tmp is writable, so DuckDB's default home (~/.duckdb) can't be
    # created and "INSTALL httpfs" fails. Point home + extension dir at /tmp before the
    # install. Harmless locally (just relocates the extension cache to /tmp).
    if os.path.isdir("/tmp"):
        con.execute("SET home_directory='/tmp'")
        con.execute("SET extension_directory='/tmp/duckdb_ext'")
    if not _needs_httpfs(source):
        return con  # local source: no extension, no network, no creds
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
