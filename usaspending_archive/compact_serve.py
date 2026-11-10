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

Before a serve file is replaced, the freshly built one is compared with the one
currently on HF (footer metadata only -- row count, column names, and action_date
min/max from row-group stats; no full download). The upload is REFUSED, and the
run exits non-zero, if rows drop by more than SHRINK_TOLERANCE, any existing column
is missing (removed or renamed), or the action_date range shrinks at either end.
Added 2026-10-23: before this, whatever the archive's All file contained -- a
truncated or partial cycle included -- silently overwrote the serve file everyone
queries. For an intentional shrink, pass --allow-shrink or set
SERVE_ALLOW_SHRINK=1 (rebuild.yml exposes it as the allow_shrink input).
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

# A routine monthly restatement moves a year's row count by well under 1%; 5% is
# a real loss, not churn.
SHRINK_TOLERANCE = 0.05
DATE_COL = "action_date"


def _truthy(v: str | None) -> bool:
    return (v or "").strip().lower() in {"1", "true", "yes"}


def parquet_summary(con: duckdb.DuckDBPyConnection, src: str) -> dict:
    """Row count, column names, and action_date min/max of one parquet file.

    Reads only the footer (works on a local path or an https URL via httpfs): the
    row count and schema are footer fields, and the date range comes from the
    row-group min/max statistics DuckDB writes. If any row group lacks stats for
    action_date, falls back to scanning that one column so the answer is still exact.
    """
    rows = con.execute(
        "SELECT num_rows FROM parquet_file_metadata(?)", [src]).fetchone()[0]
    columns = [r[0] for r in con.execute(
        f"DESCRIBE SELECT * FROM read_parquet('{src}')").fetchall()]
    min_d = max_d = None
    if DATE_COL in columns:
        n, n_stats, min_d, max_d = con.execute(
            "SELECT count(*), count(stats_max_value), "
            "min(TRY_CAST(stats_min_value AS DATE)), max(TRY_CAST(stats_max_value AS DATE)) "
            "FROM parquet_metadata(?) WHERE path_in_schema = ?", [src, DATE_COL]).fetchone()
        if n and n_stats < n:
            min_d, max_d = con.execute(
                f"SELECT min({DATE_COL}), max({DATE_COL}) FROM read_parquet('{src}')").fetchone()
    return {"rows": int(rows), "columns": columns, "min_date": min_d, "max_date": max_d}


def compare_serve(old: dict, new: dict, tolerance: float = SHRINK_TOLERANCE) -> list[str]:
    """Reasons the new serve file must not replace the old one ([] = safe)."""
    problems: list[str] = []
    if old["rows"] and new["rows"] < old["rows"] * (1 - tolerance):
        drop = 1 - new["rows"] / old["rows"]
        problems.append(f"rows dropped {old['rows']:,} -> {new['rows']:,} "
                        f"(-{drop:.1%}, tolerance {tolerance:.0%})")
    missing = [c for c in old["columns"] if c not in set(new["columns"])]
    if missing:
        problems.append(f"{len(missing)} column(s) missing from new file "
                        f"(removed or renamed): {', '.join(missing)}")
    if old["max_date"] is not None:
        if new["max_date"] is None:
            problems.append(f"{DATE_COL} range lost (old {old['min_date']}..{old['max_date']})")
        else:
            if new["max_date"] < old["max_date"]:
                problems.append(f"max({DATE_COL}) went backwards {old['max_date']} -> {new['max_date']}")
            if old["min_date"] is not None and new["min_date"] > old["min_date"]:
                problems.append(f"min({DATE_COL}) moved later {old['min_date']} -> {new['min_date']}")
    return problems


def describe_diff(old: dict, new: dict) -> str:
    added = [c for c in new["columns"] if c not in set(old["columns"])]
    return (f"rows {old['rows']:,} -> {new['rows']:,}; "
            f"columns {len(old['columns'])} -> {len(new['columns'])}"
            + (f" (+{', '.join(added)})" if added else "")
            + f"; {DATE_COL} {old['min_date']}..{old['max_date']} -> "
              f"{new['min_date']}..{new['max_date']}")


def check_before_replace(con, api, product: str, fy: str, out: Path,
                         allow_shrink: bool) -> bool:
    """Compare the new serve file at `out` with the live one. True = OK to upload."""
    path_in_repo = f"serve/{product}/{fy}.parquet"
    new = parquet_summary(con, str(out))
    if not api.file_exists(HF_REPO, path_in_repo, repo_type="dataset"):
        print(f"  {path_in_repo}: no current serve file, first publish "
              f"({new['rows']:,} rows)")
        return True
    old = parquet_summary(con, RESOLVE + path_in_repo)
    print(f"  {path_in_repo}: {describe_diff(old, new)}")
    problems = compare_serve(old, new)
    if not problems:
        return True
    for p in problems:
        print(f"    ! {p}")
    if allow_shrink:
        print("    override set (--allow-shrink / SERVE_ALLOW_SHRINK): uploading anyway")
        return True
    print(f"    REFUSED: not replacing {path_in_repo}. If this change is intentional, "
          f"re-run with --allow-shrink (rebuild.yml input allow_shrink=true).")
    return False


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--product", choices=["contracts", "assistance"], default=None)
    ap.add_argument("--years", default=None, help="comma-separated, default all present")
    ap.add_argument("--allow-shrink", action="store_true",
                    help="Upload even if the new serve file has fewer rows/columns or a "
                         "narrower action_date range than the live one (also: "
                         "SERVE_ALLOW_SHRINK=1).")
    args = ap.parse_args()
    allow_shrink = args.allow_shrink or _truthy(os.environ.get("SERVE_ALLOW_SHRINK"))

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
    refused: list[str] = []
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
            if not check_before_replace(con, api, product, fy, out, allow_shrink):
                refused.append(f"serve/{product}/{fy}.parquet")
                continue
            api.upload_file(
                path_or_fileobj=str(out), path_in_repo=f"serve/{product}/{fy}.parquet",
                repo_id=HF_REPO, repo_type="dataset",
                commit_message=f"serve {product} {fy} ({rows:,} rows)",
            )
        print(f"  serve/{product}/{fy}.parquet  {rows:,} rows  {out.stat().st_size/1e6:.0f}MB  {time.time()-ts:.0f}s"
              if out.exists() else f"  serve/{product}/{fy}.parquet  {rows:,} rows")
        time.sleep(1)
    if refused:
        print(f"\nFAILED: refused to replace {len(refused)} serve file(s): {', '.join(refused)}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
