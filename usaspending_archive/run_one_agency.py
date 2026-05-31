"""Phase-1 proof: fetch -> typed partitioned Parquet for ONE agency, all FYs.

Usage:
    python -m usaspending_archive.run_one_agency 389          # one agency, both products
    python -m usaspending_archive.run_one_agency 097 --product Contracts

Prints per-file rows/cols/CSV/Parquet sizes + totals, so we can extrapolate the
full-corpus footprint and backfill time before committing to all 91 GB.
"""
from __future__ import annotations

import argparse
import time
from pathlib import Path

import duckdb

from .archive_index import list_archive, latest_datestamp
from .convert import csv_to_parquet, partition_path
from .fetch import download_zip, extract_csvs

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("agency")
    ap.add_argument("--product", choices=["Contracts", "Assistance"], default=None,
                    help="default: both")
    args = ap.parse_args()

    print("listing archive...")
    files = list_archive()
    ds = latest_datestamp(files)
    products = [args.product] if args.product else ["Contracts", "Assistance"]
    todo = [f for f in files
            if f.agency_code == args.agency and f.kind == "Full"
            and f.datestamp == ds and f.award_type in products]
    todo.sort(key=lambda f: (f.award_type, f.fiscal_year))
    if not todo:
        print(f"no Full files for agency {args.agency} at datestamp {ds}")
        return

    con = duckdb.connect()
    tmp = DATA / "_tmp"
    tot_csv = tot_pq = tot_rows = 0
    t0 = time.time()
    print(f"\n{'file':52s} {'rows':>10s} {'cols':>5s} {'CSV MB':>8s} {'PQ MB':>7s} {'s':>5s}")
    for f in todo:
        ts = time.time()
        time.sleep(1.0)  # be polite to the CDN
        zp = download_zip(f.url)
        if isinstance(zp, str):
            print(f"{f.key:52s}  -> {zp}")
            continue
        csvs = extract_csvs(zp, tmp / f.key.replace(".zip", ""))
        csv_bytes = sum(c.stat().st_size for c in csvs)
        # stable name (no datestamp) so refreshes overwrite — latest-only; datestamp lives in the manifest
        out = partition_path(DATA, f.award_type.lower(), f.fiscal_year, f.agency_code, "part")
        info = csv_to_parquet(csvs, out, con)
        dt = time.time() - ts
        tot_csv += csv_bytes; tot_pq += info["bytes"]; tot_rows += info["rows"]
        print(f"{f.key:52s} {info['rows']:>10,} {info['cols']:>5} "
              f"{csv_bytes/1e6:>8.1f} {info['bytes']/1e6:>7.1f} {dt:>5.1f}")
        zp.unlink(missing_ok=True)
        for c in csvs:
            c.unlink(missing_ok=True)

    elapsed = time.time() - t0
    print(f"\nTOTAL  rows={tot_rows:,}  CSV={tot_csv/1e6:.1f}MB  "
          f"Parquet={tot_pq/1e6:.1f}MB  ({tot_csv/max(tot_pq,1):.2f}x smaller)  "
          f"in {elapsed:.0f}s")
    print(f"output tree: {DATA}")


if __name__ == "__main__":
    main()
