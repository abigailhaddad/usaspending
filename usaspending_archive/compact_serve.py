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

# 2026-11-09: count a transaction USASpending re-published only once (contracts).
# USASpending's 20261106 archive has a second row for 15,567 FY2026 DoD transactions
# that FPDS records once: same award, modification number, action date and amount, a
# different transaction_number / contract_transaction_unique_key, and a
# last_modified_date of 2026-11-02 (13,379), 11-03 (20) or 11-04 (2,168) next to an
# older copy. FPDS shows DoD edited those records 2026-11-02..04; USASpending added the
# edited ones beside the old (reported: fedspendingtransparency/usaspending-api#4855).
# FPDS check, 2026-11-09: 33 of 33 such groups (30 random + Raytheon W31P4Q26C0001,
# Lockheed W31P4Q26C0019, W31P4Q25C0007) have ONE FPDS record.
# Scoped to the reload window on purpose: older repeated rows are a mix. Of 15 older
# pairs whose copies were last modified >2 days apart, FPDS had one record for 11 and
# two for 4 (H9240824C6972 P00010, $51.1M, is two real FPDS transactions 14 and 16),
# so a gap-only rule would drop real money. Rule: a row last modified inside a listed
# window is dropped when another row of its (award, modification, action date, amount)
# group was last modified before that window. Add a window only after checking FPDS.
# The raw layer is untouched; only serve/ is cleaned. Same table as
# pull_usaspending/reload_duplicates.py.
RELOAD_WINDOWS = [  # (first day, last day, where it was reported)
    ("2026-11-02", "2026-11-04", "fedspendingtransparency/usaspending-api#4855"),
]


def reload_dedupe_select(src: str) -> str:
    """SELECT over `src` (a read_parquet(...) expression) without the re-published
    copies (RELOAD_WINDOWS). Order-independent: the window takes the group's earliest."""
    drop = " OR ".join(
        f"(last_modified_date BETWEEN DATE '{lo}' AND DATE '{hi}' AND _first_lm < DATE '{lo}')"
        for lo, hi, _ in RELOAD_WINDOWS)
    return (
        f"SELECT * EXCLUDE (_first_lm) FROM ("
        f" SELECT *, min(last_modified_date) OVER (PARTITION BY contract_award_unique_key,"
        f" modification_number, action_date, round(federal_action_obligation, 2)) AS _first_lm"
        f" FROM {src}) t"
        f" WHERE NOT coalesce({drop}, false)"
    )

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
            src = f"read_parquet({files}, union_by_name=true)"
            select = reload_dedupe_select(src) if product == "contracts" else f"SELECT * FROM {src}"
            con.execute(f"COPY ({select}) TO '{out}' (FORMAT parquet, COMPRESSION zstd)")
            rows = con.execute(f"SELECT count(*) FROM read_parquet('{out}')").fetchone()[0]
            if product == "contracts":
                n_in, usd_in = con.execute(
                    f"SELECT count(*), coalesce(sum(federal_action_obligation), 0) FROM {src}").fetchone()
                usd_out = con.execute(
                    f"SELECT coalesce(sum(federal_action_obligation), 0) FROM read_parquet('{out}')").fetchone()[0]
                print(f"  reload copies dropped: {n_in - rows:,} rows, ${usd_in - usd_out:,.2f}")
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
