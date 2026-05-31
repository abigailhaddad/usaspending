"""List the USAspending Award Data Archive.

The archive is an S3 bucket (`dti-usaspending-monthly-downloads`) exposed at
https://files.usaspending.gov/award_data_archive/ . It publishes four products,
one file per agency:

    {Contracts,Assistance}_Full   per agency x fiscal year   (full snapshot)
    {Contracts,Assistance}_Delta  FY(All) x agency           (monthly changes)

There are NO subaward or account (File A/B/C) files here. Those come only from
the Custom Bulk Download API (see docs/FINDINGS.md).

Ported from pull_usaspending/pull_usaspending/scan.py, generalized to all four
products and to full pagination (the bucket lists 1000 keys/page).
"""
from __future__ import annotations

import json
import re
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from collections import defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path

ARCHIVE_BASE = "https://files.usaspending.gov/award_data_archive/"
_NS = "{http://s3.amazonaws.com/doc/2006-03-01/}"

# FY{year|(All)}_{agencycode}_{Contracts|Assistance}_{Full|Delta}_{YYYYMMDD}.zip
_KEY_RE = re.compile(
    r"^FY\(?(?P<fy>\d{4}|All)\)?_(?P<agency>[^_]+)_"
    r"(?P<award>Contracts|Assistance)_(?P<kind>Full|Delta)_(?P<date>\d{8})\.zip$"
)


@dataclass(frozen=True)
class ArchiveFile:
    key: str
    size: int
    etag: str          # S3 MD5 (quoted) — the change-detection key
    fiscal_year: str   # "2024" or "All"
    agency_code: str
    award_type: str    # "Contracts" | "Assistance"
    kind: str          # "Full" | "Delta"
    datestamp: str     # "YYYYMMDD"

    @property
    def url(self) -> str:
        return ARCHIVE_BASE + self.key


_CACHE = Path(__file__).resolve().parent.parent / "scratch" / "archive_index.json"


def _get(url: str, timeout: int, retries: int = 6) -> bytes:
    """Fetch a URL, retrying with backoff (the CDN throttles bursts)."""
    for attempt in range(retries):
        try:
            return urllib.request.urlopen(url, timeout=timeout).read()
        except Exception:
            if attempt == retries - 1:
                raise
            time.sleep(min(5 * 2 ** attempt, 120))


def list_archive(timeout: int = 60, use_cache: bool = True) -> list[ArchiveFile]:
    """Paginate the full bucket listing and return every parseable archive file.

    Caches the parsed listing to scratch/archive_index.json so repeated runs don't
    re-hit (and re-trip) the throttle. Pass use_cache=False to force a refresh.
    """
    if use_cache and _CACHE.exists():
        return [ArchiveFile(**d) for d in json.loads(_CACHE.read_text())]
    out: list[ArchiveFile] = []
    marker = ""
    while True:
        url = ARCHIVE_BASE + ("?marker=" + urllib.parse.quote(marker) if marker else "")
        root = ET.fromstring(_get(url, timeout))
        contents = root.findall(_NS + "Contents")
        if not contents:
            break
        for c in contents:
            key = c.find(_NS + "Key").text
            m = _KEY_RE.match(key)
            if not m:
                continue
            out.append(ArchiveFile(
                key=key,
                size=int(c.find(_NS + "Size").text),
                etag=(c.find(_NS + "ETag").text or "").strip('"'),
                fiscal_year=m.group("fy"),
                agency_code=m.group("agency"),
                award_type=m.group("award"),
                kind=m.group("kind"),
                datestamp=m.group("date"),
            ))
        if (root.find(_NS + "IsTruncated").text or "false") != "true":
            break
        marker = contents[-1].find(_NS + "Key").text
    _CACHE.parent.mkdir(parents=True, exist_ok=True)
    _CACHE.write_text(json.dumps([asdict(f) for f in out]))
    return out


def latest_datestamp(files: list[ArchiveFile]) -> str:
    """Most recent datestamp present in the archive (the current publish cycle)."""
    return max(f.datestamp for f in files)


def summarize(files: list[ArchiveFile]) -> None:
    """Print the inventory table from docs/FINDINGS.md."""
    by_prod: dict[tuple[str, str], list[int]] = defaultdict(lambda: [0, 0])
    fys: set[str] = set()
    for f in files:
        rec = by_prod[(f.award_type, f.kind)]
        rec[0] += 1
        rec[1] += f.size
        fys.add(f.fiscal_year)
    print(f"{len(files)} keys, latest datestamp {latest_datestamp(files)}")
    print(f"{'product':24s} {'files':>6s} {'GB':>9s}")
    for (award, kind), (n, sz) in sorted(by_prod.items(), key=lambda x: -x[1][1]):
        print(f"{award + '_' + kind:24s} {n:6d} {sz / 1e9:9.2f}")
    print(f"{'TOTAL':24s} {len(files):6d} {sum(f.size for f in files) / 1e9:9.2f}")
    print("FY range:", ", ".join(sorted(fys)))


if __name__ == "__main__":
    summarize(list_archive())
