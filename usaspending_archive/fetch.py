"""Download + unzip archive files.

Ported from pull_usaspending/pull_usaspending/scan.py (download_zip), kept the
streaming download + retry/sentinel behavior, generalized to return the extracted
CSV path(s). A single archive zip can contain more than one CSV (USAspending
splits large agency-years into `..._1.csv`, `..._2.csv`).
"""
from __future__ import annotations

import tempfile
import time
import zipfile
from pathlib import Path

import requests

NOT_FOUND = "NOT_FOUND"
IP_BLOCKED = "IP_BLOCKED"
FAILED = "FAILED"


def download_zip(url: str, max_retries: int = 5) -> Path | str:
    """Stream a zip to a temp file. Returns the temp path or a sentinel string.

    USAspending's CDN throttles rapid sequential requests, surfacing as 5xx or
    dropped connections. Both are transient, so we back off and retry rather than
    bailing immediately; IP_BLOCKED is only returned after retries are exhausted.
    """
    last = IP_BLOCKED
    for attempt in range(max_retries):
        try:
            r = requests.get(url, stream=True, timeout=600)
            if r.status_code == 404:
                return NOT_FOUND
            if r.status_code >= 500:
                last = IP_BLOCKED
                time.sleep(min(5 * 2 ** attempt, 120))
                continue
            r.raise_for_status()
            tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".zip")
            for chunk in r.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    tmp.write(chunk)
            tmp.close()
            return Path(tmp.name)
        except requests.exceptions.ConnectionError:
            last = IP_BLOCKED
            time.sleep(min(5 * 2 ** attempt, 120))
        except Exception:
            last = FAILED
            time.sleep(min(30 * (attempt + 1), 180))
    return last


def extract_csvs(zip_path: Path, dest: Path) -> list[Path]:
    """Extract all .csv members of a zip into dest. Returns the extracted paths."""
    dest.mkdir(parents=True, exist_ok=True)
    out: list[Path] = []
    with zipfile.ZipFile(zip_path) as z:
        for member in z.namelist():
            if member.lower().endswith(".csv"):
                z.extract(member, dest)
                out.append(dest / member)
    return out
