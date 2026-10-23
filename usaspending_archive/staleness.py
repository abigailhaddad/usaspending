"""Is the HF mirror behind the USAspending archive? (weekly check, staleness.yml)

Added 2026-10-23. Every failure mode found in the 10-23 review -- a skipped file,
a re-chain loop, a Delta-dated "latest" -- left the daily refresh green while the
mirror fell behind, so nothing ever told anyone. This compares three dates:

    archive   newest Full datestamp in the live archive listing (the current cycle)
    manifest  newest datestamp recorded in metadata/manifest.json (what we ingested)
    serve     max(action_date) across serve/contracts/{current, prior FY}.parquet
              on HF (footer stats only -- what people actually query)

and reports STALE if the manifest or the serve layer trails the archive cycle by
more than --max-lag-days (default 40: one monthly cycle plus slack, so a single
missed cycle trips it). staleness.yml opens or comments on a GitHub issue on STALE.

What it can't see: a future-dated action_date in a serve file pushes serve's max
forward and can hide a stale serve layer (the manifest comparison still catches a
stalled ingest). It also says nothing about whether the archive itself stopped
publishing; that age is printed for context but doesn't trigger the alert.

    python -m usaspending_archive.staleness                       # print report
    python -m usaspending_archive.staleness --report staleness.md  # + write it
"""
from __future__ import annotations

import argparse
import datetime as dt
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MANIFEST = ROOT / "metadata" / "manifest.json"
DEFAULT_MAX_LAG_DAYS = 40


def _d(stamp: str) -> dt.date:
    return dt.datetime.strptime(stamp, "%Y%m%d").date()


def manifest_latest(m: dict) -> str | None:
    """Newest datestamp the manifest records (backfill only ingests Full files)."""
    stamps = [e.get("datestamp") for e in m.values() if e.get("datestamp")]
    return max(stamps) if stamps else None


def current_fy(today: dt.date) -> int:
    return today.year + 1 if today.month >= 10 else today.year


def assess(*, archive_full: str, manifest_stamp: str | None, serve_max: dt.date | None,
           today: dt.date, max_lag_days: int = DEFAULT_MAX_LAG_DAYS) -> tuple[bool, list[str]]:
    """(stale, report lines). Pure: all inputs already fetched."""
    a = _d(archive_full)
    lines = [f"- Archive: latest **Full** datestamp `{archive_full}` "
             f"({(today - a).days} days before this check, {today.isoformat()})"]
    problems: list[str] = []

    if manifest_stamp is None:
        problems.append("manifest has no datestamps")
        lines.append("- Manifest: **no entries with a datestamp**")
    else:
        lag = (a - _d(manifest_stamp)).days
        lines.append(f"- Manifest: latest ingested datestamp `{manifest_stamp}` "
                     f"(**{lag} days** behind the archive cycle)")
        if lag > max_lag_days:
            problems.append(f"manifest is {lag} days behind the archive")

    if serve_max is None:
        problems.append("no serve/contracts file for the current or prior FY")
        lines.append("- Serve: **no serve/contracts file found** for the current or prior FY")
    else:
        lag = (a - serve_max).days
        lines.append(f"- Serve: max(action_date) in serve/contracts (current + prior FY) "
                     f"`{serve_max.isoformat()}` (**{lag} days** behind the archive cycle)")
        if lag > max_lag_days:
            problems.append(f"serve layer is {lag} days behind the archive")

    lines.append(f"- Threshold: {max_lag_days} days")
    if problems:
        lines.insert(0, "**STALE:** " + "; ".join(problems) + ".\n")
    else:
        lines.insert(0, "OK: mirror is within the threshold.\n")
    return bool(problems), lines


def serve_max_action_date(today: dt.date) -> dt.date | None:
    """max(action_date) over serve/contracts/{FY, FY-1}.parquet that exist on HF."""
    import duckdb
    from huggingface_hub import HfApi

    from .compact_serve import HF_REPO, RESOLVE, parquet_summary

    api = HfApi(token=False)  # public dataset: anonymous, like the CI runner
    con = duckdb.connect()
    con.execute("INSTALL httpfs; LOAD httpfs;")
    fy = current_fy(today)
    best: dt.date | None = None
    for y in (fy, fy - 1):
        path = f"serve/contracts/{y}.parquet"
        if not api.file_exists(HF_REPO, path, repo_type="dataset"):
            print(f"  {path}: not on HF")
            continue
        s = parquet_summary(con, RESOLVE + path)
        print(f"  {path}: {s['rows']:,} rows, action_date {s['min_date']}..{s['max_date']}")
        if s["max_date"] is not None and (best is None or s["max_date"] > best):
            best = s["max_date"]
    return best


def main(argv: list[str] | None = None) -> int:
    from . import manifest
    from .archive_index import latest_datestamp, list_archive

    ap = argparse.ArgumentParser()
    ap.add_argument("--max-lag-days", type=int, default=DEFAULT_MAX_LAG_DAYS)
    ap.add_argument("--report", default=None, help="also write the markdown report here")
    args = ap.parse_args(argv)

    today = dt.datetime.now(dt.timezone.utc).date()
    archive_full = latest_datestamp(list_archive(use_cache=False), kind="Full")
    m = manifest.load(MANIFEST)
    serve_max = serve_max_action_date(today)
    stale, lines = assess(archive_full=archive_full, manifest_stamp=manifest_latest(m),
                          serve_max=serve_max, today=today, max_lag_days=args.max_lag_days)
    body = "\n".join(lines)
    print("\n" + body)
    if args.report:
        Path(args.report).write_text(body + "\n")
    gh = os.environ.get("GITHUB_OUTPUT")
    if gh:
        with open(gh, "a") as f:
            f.write(f"stale={'true' if stale else 'false'}\n")
    # Exit 0 either way: staleness.yml reads `stale` to file the issue, then fails
    # the run itself. A non-zero exit here means the CHECK broke (network, parse).
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
