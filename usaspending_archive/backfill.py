"""Backfill / refresh the HF dataset from the archive — resumable, chain-on-block.

For each (product, FY, agency) Full file whose ETag is new or changed vs the
manifest: download -> convert to typed parquet -> upload to HF at the stable
partition key -> record in the manifest. The manifest is saved after every file,
so a chained run (fresh runner IP) resumes exactly where this one stopped.

The CDN locks an IP out after ~15-20 files (validated 2026-05-31), so on the
first IP_BLOCKED we stop and print CHAIN_NEEDED; the workflow then dispatches a
fresh run. R2 mirroring is deferred (HF-only for now).

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
from .fetch import IP_BLOCKED, NOT_FOUND, download_zip, extract_csvs
from .publish import publish_to_hf

ROOT = Path(__file__).resolve().parent.parent
MANIFEST = ROOT / "metadata" / "manifest.json"
HF_REPO = os.environ.get("HF_REPO", "abigailhaddad/usaspending-bulk-awards")


def _default_fiscal_years() -> set[str]:
    """Current + prior federal fiscal year (Oct-Sep). Mirrors rebuild.yml's FY math:
    a monthly source refresh only meaningfully restates these two years."""
    now = datetime.datetime.now(datetime.timezone.utc)
    fy = now.year + 1 if now.month >= 10 else now.year
    return {str(fy), str(fy - 1)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-files", type=int, default=200)
    ap.add_argument("--agency", default=None)
    ap.add_argument("--product", choices=["Contracts", "Assistance"], default=None)
    ap.add_argument("--fiscal-years", default=None,
                    help="Comma-separated FYs to limit to, e.g. '2025,2026'. "
                         "Blank = current + prior fiscal year (the normal refresh "
                         "window). Pass 'all' for a full-catalog re-ingest, e.g. when "
                         "the source restates ETags across every year.")
    ap.add_argument("--stalled-hops", type=int, default=0,
                    help="Consecutive earlier hops of this chain that were IP-blocked "
                         "before ingesting anything (refresh.yml carries it; 0 by hand).")
    ap.add_argument("--max-stalled-hops", type=int, default=MAX_STALLED_HOPS)
    args = ap.parse_args()

    # Blank -> current + prior FY (what a monthly source refresh actually restates);
    # 'all' -> no filter. Bounding here stops a source-wide ETag shuffle from
    # dragging the whole back-catalog through a re-ingest.
    if args.fiscal_years and args.fiscal_years.strip().lower() == "all":
        fy_filter = None
    elif args.fiscal_years:
        fy_filter = {y.strip() for y in args.fiscal_years.split(",") if y.strip()}
    else:
        fy_filter = _default_fiscal_years()
    if fy_filter is not None:
        print(f"limiting to fiscal years: {','.join(sorted(fy_filter))}")

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
    if fy_filter:
        todo = [f for f in todo if f.fiscal_year in fy_filter]
    # newest fiscal years first — recent spending is what most analyses want
    todo.sort(key=lambda f: f.fiscal_year, reverse=True)
    total_todo = len(todo)
    # NOT_FOUND files never get staged, so they must not eat the --max-files slice
    # (else the same dead files fill every run's slice and nothing progresses); the
    # loop below stops once max_files files are staged instead.
    print(f"{total_todo} changed files; processing up to {min(total_todo, args.max_files)} this run; HF repo {HF_REPO}")

    con = duckdb.connect()
    done = 0
    blocked = False
    not_found = 0
    error: Exception | None = None
    # Download + convert a batch locally, then push it as ONE HF commit. HF rate-limits
    # commits (429), so one-commit-per-file does NOT scale — one commit per run does.
    # Everything is wrapped so an unexpected error still reaches the summary lines
    # and the manifest stays consistent; _chain_decision then refuses to chain on a
    # non-IP error (2026-11-09) instead of re-dispatching into the same failure.
    try:
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            staged: list[tuple[Path, str, object, dict]] = []  # (parquet, key, file, info)
            for f in todo:
                if len(staged) >= args.max_files:
                    break
                zp = download_zip(f.url)
                if isinstance(zp, str):
                    print(f"{f.key}  -> {zp}")
                    if zp == IP_BLOCKED:
                        blocked = True
                        break
                    if zp == NOT_FOUND:
                        not_found += 1
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
        error = exc
        print(f"ERROR (progress through last commit is saved): {exc}")

    # NOT_FOUND files (listed but 404) stay in `changed` forever; counting them as
    # remaining made every run print CHAIN_NEEDED and re-dispatch endlessly.
    remaining = total_todo - done - not_found
    print(f"\nprocessed {done}, {remaining} changed files remain")
    if not_found:
        print(f"{not_found} listed files returned NOT_FOUND (not counted as remaining)")
    return _chain_decision(blocked=blocked, error=error, done=done, remaining=remaining,
                           stalled_hops=args.stalled_hops, max_stalled_hops=args.max_stalled_hops)


# 2026-11-10 (ported from the unmerged 2026-10-23 PR #2): an IP block chains for a
# fresh runner, but a block that never lifts -- every hop blocked before its first
# file -- would chain forever, each hop green. Cap consecutive zero-progress blocked
# hops. A long --fiscal-years all re-ingest is many hops, but each makes progress.
MAX_STALLED_HOPS = 3


def _chain_decision(*, blocked: bool, error: Exception | None, done: int, remaining: int,
                    stalled_hops: int = 0, max_stalled_hops: int = MAX_STALLED_HOPS) -> int:
    """Print CHAIN_NEEDED only when a fresh run can make progress; return the exit code.

    2026-11-09: this used to chain whenever files remained -- including after an
    unexpected exception. A deterministic error (a column typed DOUBLE that fails
    the same file every time) then looped: 93 runs in about an hour, each failing
    on its first file and dispatching the next, every one reported green. Now:
      - IP block                             -> chain (fresh runner, fresh IP); exit 0,
        unless this is the (max_stalled_hops+1)th hop in a row blocked before any
        file landed -> no chain; exit 1
      - any other error                      -> no chain; exit 1 so the run fails loudly
      - progress made, files left (max_files) -> chain; exit 0
      - no progress, no block, files left    -> no chain; exit 1 (would loop)
    """
    if error is not None and not blocked:
        print(f"::error::backfill stopped on an error, not an IP block -- not chaining: {error}")
        return 1
    if blocked and done == 0 and stalled_hops + 1 > max_stalled_hops:
        print(f"::error::IP-blocked before any file landed on {stalled_hops + 1} hops in a row "
              f"(cap {max_stalled_hops}) -- not chaining")
        return 1
    if blocked or (remaining > 0 and done > 0):
        print("CHAIN_NEEDED")
        return 0
    if remaining > 0:
        print("::error::no file was ingested and the run was not IP-blocked -- not chaining")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
