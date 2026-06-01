"""Build the query-optimized SERVING layer: one parquet per (product, fiscal year).

The raw layer is one file per (product, FY, agency) — thousands of files. Globbing that
over hf:// makes DuckDB recursively list every partition dir, which HuggingFace rate-limits
(HTTP 429). This compacts each fiscal year's per-agency files into a single file at

    serve/{product}/{fy}.parquet

so queries glob ~20 files per product instead of thousands — no listing storm, no 429.

Critically, compaction reads the per-agency files by EXPLICIT URL list from the manifest
(never a glob), so it doesn't trigger the listing rate-limit itself.

    python -m usaspending_archive.compact_serve            # all years present in the manifest
    python -m usaspending_archive.compact_serve --product contracts --years 2024,2025,2026
"""
from __future__ import annotations

import argparse
import json
import os
import tempfile
import time
from collections import defaultdict
from pathlib import Path

import duckdb

from .manifest import load

HF_REPO = "abigailhaddad/usaspending-bulk-awards"
ROOT = Path(__file__).resolve().parent.parent
MANIFEST = ROOT / "metadata" / "manifest.json"
RESOLVE = f"https://huggingface.co/datasets/{HF_REPO}/resolve/main/"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--product", choices=["contracts", "assistance"], default=None)
    ap.add_argument("--years", default=None, help="comma-separated, default all present")
    args = ap.parse_args()

    from huggingface_hub import HfApi
    api = HfApi(token=os.environ["HF_TOKEN"])

    m = load(MANIFEST)
    groups: dict[tuple[str, str], list[str]] = defaultdict(list)
    all_url = {}  # (product, fy) -> the archive's complete per-year "All" file
    for logical_id, e in m.items():
        product, fy, code = logical_id.split("/")
        if args.product and product != args.product:
            continue
        if args.years and fy not in args.years.split(","):
            continue
        if code == "All":
            all_url[(product, fy)] = RESOLVE + e["parquet_key"]
        else:
            groups[(product, fy)].append(RESOLVE + e["parquet_key"])

    con = duckdb.connect()
    con.execute("INSTALL httpfs; LOAD httpfs;")
    con.execute("SET memory_limit='12GB'; SET temp_directory='/tmp/duckspill';")  # spill, don't OOM
    keys = sorted(set(list(all_url) + list(groups)))
    print(f"compacting {len(keys)} (product, year) groups → serve/")
    for (product, fy) in keys:
        # The archive already ships a complete per-year "All" file — use it (one file, no
        # merge, no double-count). Only fall back to merging per-agency files if All is absent.
        urls = [all_url[(product, fy)]] if (product, fy) in all_url else groups[(product, fy)]
        ts = time.time()
        files = "[" + ", ".join("'" + u + "'" for u in urls) + "]"
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / f"{fy}.parquet"
            con.execute(
                f"COPY (SELECT * FROM read_parquet({files}, union_by_name=true)) "
                f"TO '{out}' (FORMAT parquet, COMPRESSION zstd)"
            )
            rows = con.execute(f"SELECT count(*) FROM read_parquet('{out}')").fetchone()[0]
            api.upload_file(
                path_or_fileobj=str(out), path_in_repo=f"serve/{product}/{fy}.parquet",
                repo_id=HF_REPO, repo_type="dataset",
                commit_message=f"serve {product} {fy} ({rows:,} rows)",
            )
        print(f"  serve/{product}/{fy}.parquet  {rows:,} rows  {out.stat().st_size/1e6:.0f}MB  {time.time()-ts:.0f}s"
              if out.exists() else f"  serve/{product}/{fy}.parquet  {rows:,} rows")
        time.sleep(1)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
