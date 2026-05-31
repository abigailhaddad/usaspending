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


def download_zip(url: str, max_retries: int = 2) -> Path | str:
    """Stream a zip to a temp file. Returns the temp path or a sentinel string.

    USAspending's CDN locks an IP out for an extended window after ~15–20 requests
    (validated on GitHub runners, 2026-05-31). Once that happens, retrying is futile
    — the proven fix is to STOP and let a fresh chained run (new runner IP) continue
    (see pull_usaspending/scan.py + scan.yml). So we only do a couple of short retries
    to ride out a genuine transient blip, then return IP_BLOCKED quickly; the caller
    is responsible for ending the run on IP_BLOCKED rather than grinding through it.
    """
    for attempt in range(max_retries):
        try:
            r = requests.get(url, stream=True, timeout=600)
            if r.status_code == 404:
                return NOT_FOUND
            if r.status_code >= 500:
                time.sleep(3 * (attempt + 1))
                continue
            r.raise_for_status()
            tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".zip")
            for chunk in r.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    tmp.write(chunk)
            tmp.close()
            return Path(tmp.name)
        except requests.exceptions.ConnectionError:
            time.sleep(3 * (attempt + 1))
        except Exception:
            return FAILED
    return IP_BLOCKED


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
