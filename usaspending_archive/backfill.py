"""Backfill / refresh the HF dataset from the archive — resumable, chain-on-block.

For each (product, FY, agency) Full file whose ETag is new or changed vs the
manifest: download -> convert to typed parquet -> upload to HF at the stable
partition key -> record in the manifest. The manifest is saved after every file,
so a chained run (fresh runner IP) resumes exactly where this one stopped.

The CDN locks an IP out after ~15-20 files (validated 2026-05-31), so on the
first IP_BLOCKED we stop and print CHAIN_NEEDED; the workflow then dispatches a
fresh run. R2 mirroring is deferred (HF-only for now) — see docs/PLAN.md.

    python -m usaspending_archive.backfill                 # drain next slice
    python -m usaspending_archive.backfill --max-files 15  # cap per run
    python -m usaspending_archive.backfill --agency 097    # one agency
"""
from __future__ import annotations

import argparse
import datetime
import os
import tempfile
from pathlib import Path

import duckdb

from . import manifest
from .archive_index import list_archive
from .convert import csv_to_parquet
from .fetch import IP_BLOCKED, download_zip, extract_csvs
from .publish import publish_to_hf

ROOT = Path(__file__).resolve().parent.parent
MANIFEST = ROOT / "metadata" / "manifest.json"
HF_REPO = os.environ.get("HF_REPO", "abigailhaddad/usaspending-bulk-awards")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-files", type=int, default=200)
    ap.add_argument("--agency", default=None)
    ap.add_argument("--product", choices=["Contracts", "Assistance"], default=None)
    args = ap.parse_args()

    from huggingface_hub import HfApi
    api = HfApi(token=os.environ["HF_TOKEN"])
    api.create_repo(HF_REPO, repo_type="dataset", exist_ok=True, private=True)

    m = manifest.load(MANIFEST)
    files = list_archive()
    todo = manifest.changed(files, m)
    if args.agency:
        todo = [f for f in todo if f.agency_code == args.agency]
    if args.product:
        todo = [f for f in todo if f.award_type == args.product]
    # newest fiscal years first — recent spending is what most analyses want
    todo.sort(key=lambda f: f.fiscal_year, reverse=True)
    total_todo = len(todo)
    todo = todo[:args.max_files]
    print(f"{total_todo} changed files; processing up to {len(todo)} this run; HF repo {HF_REPO}")

    con = duckdb.connect()
    done = 0
    blocked = False
    # Download + convert a batch locally, then push it as ONE HF commit. HF rate-limits
    # commits (429), so one-commit-per-file does NOT scale — one commit per run does.
    # Everything is wrapped so an unexpected error still exits cleanly and signals the
    # chain (work remains) rather than crashing before CHAIN_NEEDED is printed.
    try:
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            staged: list[tuple[Path, str, object, dict]] = []  # (parquet, key, file, info)
            for f in todo:
                zp = download_zip(f.url)
                if isinstance(zp, str):
                    print(f"{f.key}  -> {zp}")
                    if zp == IP_BLOCKED:
                        blocked = True
                        break
                    continue
                csvs = extract_csvs(zp, tmp / manifest.logical_id(f).replace("/", "_"))
                parquet = tmp / (manifest.logical_id(f).replace("/", "_") + ".parquet")
                info = csv_to_parquet(csvs, parquet, con)
                staged.append((parquet, manifest.parquet_key(f), f, info))
                print(f"{manifest.parquet_key(f):55s} {info['rows']:>9,} rows  {info['bytes']/1e6:6.1f}MB")
                zp.unlink(missing_ok=True)
                for c in csvs:
                    c.unlink(missing_ok=True)

            if staged:
                publish_to_hf([(p, k) for p, k, _, _ in staged], HF_REPO,
                              batch_size=len(staged))  # single commit for the whole run
                now = datetime.datetime.now(datetime.timezone.utc).isoformat()
                for _, _, f, info in staged:
                    manifest.record(m, f, rows=info["rows"], parquet_bytes=info["bytes"],
                                    updated_at=now)
                manifest.save(MANIFEST, m)
                done = len(staged)
    except Exception as exc:
        print(f"ERROR (progress through last commit is saved): {exc}")

    remaining = total_todo - done
    print(f"\nprocessed {done}, {remaining} changed files remain")
    if blocked or remaining > 0:
        print("CHAIN_NEEDED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
