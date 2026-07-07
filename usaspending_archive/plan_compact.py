"""Emit the compaction matrix for the rebuild workflow — one shard per (product, year).

Reads the manifest and honors two env inputs:
  PRODUCT = contracts | assistance | both   (default both)
  YEARS   = recent | all | "2024,2025,2026"  (default recent)

'recent' = the two newest fiscal years present per product — the only ones that change
between USAspending drops, so a routine/chained run stays small. 'all' = every present
year, each as its own matrix shard so a full backfill runs as many short parallel jobs
instead of one 6-hour serial job.

Writes GitHub Actions step outputs (to $GITHUB_OUTPUT):
  matrix={"include":[{"product":..., "year":...}, ...]}
  empty=true|false

    PRODUCT=both YEARS=recent python -m usaspending_archive.plan_compact
"""
from __future__ import annotations

import json
import os
import sys
from collections import defaultdict
from pathlib import Path

MANIFEST = Path(__file__).resolve().parent.parent / "metadata" / "manifest.json"


def plan(product: str, years: str) -> list[dict]:
    m = json.load(open(MANIFEST))
    present: dict[str, set] = defaultdict(set)
    for logical_id in m:
        p, fy, _code = logical_id.split("/")
        present[p].add(fy)

    products = ["contracts", "assistance"] if product == "both" else [product]
    combos: list[dict] = []
    for p in products:
        fys = sorted(present.get(p, []))
        if not fys:
            continue
        if years == "recent":
            pick = fys[-2:]                       # two newest present FYs
        elif years == "all":
            pick = fys
        else:
            want = {y.strip() for y in years.split(",")}
            pick = [y for y in fys if y in want]  # explicit list, filtered to what exists
        combos += [{"product": p, "year": y} for y in pick]
    return combos


def main() -> int:
    product = (os.environ.get("PRODUCT") or "both").strip() or "both"
    years = (os.environ.get("YEARS") or "recent").strip() or "recent"
    combos = plan(product, years)
    lines = [
        f"matrix={json.dumps({'include': combos})}",
        f"empty={'true' if not combos else 'false'}",
    ]
    gh = os.environ.get("GITHUB_OUTPUT")
    if gh:
        with open(gh, "a") as f:
            f.write("\n".join(lines) + "\n")
    # Echo to the log so the plan is visible in the run.
    print(f"product={product} years={years} -> {len(combos)} shard(s)", file=sys.stderr)
    print("\n".join(lines), file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
