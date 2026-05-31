"""ETag-based change detection.

The archive re-publishes every Full file each cycle under a new datestamp, but
most old-FY files are byte-identical. The S3 listing exposes an ETag (MD5) per
key, so we only re-process a (product, FY, agency) when its ETag changes — the
manifest is the record of "what we've already published, and from which ETag."

Manifest shape (metadata/manifest.json):

    {
      "contracts/2024/097": {
        "etag": "abc...", "datestamp": "20260506",
        "rows": 123456, "parquet_bytes": 9876543,
        "parquet_key": "contracts/fiscal_year=2024/agency=097/part.parquet",
        "updated_at": "<stamped by caller>"
      },
      ...
    }

Modeled on opm/opm_pipeline/manifest.py. Latest-only: one entry per logical id,
overwritten on change (no per-month history; the etag/datestamp is the audit trail).
"""
from __future__ import annotations

import json
from pathlib import Path

from .archive_index import ArchiveFile


def logical_id(f: ArchiveFile) -> str:
    """Datestamp-independent identity of a file: '{product}/{fy}/{agency}'."""
    return f"{f.award_type.lower()}/{f.fiscal_year}/{f.agency_code}"


def parquet_key(f: ArchiveFile) -> str:
    """Stable Hive-partitioned path within the dataset (no datestamp)."""
    return (f"{f.award_type.lower()}/fiscal_year={f.fiscal_year}"
            f"/agency={f.agency_code}/part.parquet")


def load(path: Path) -> dict:
    return json.loads(path.read_text()) if path.exists() else {}


def save(path: Path, manifest: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, indent=2, sort_keys=True))


def changed(files: list[ArchiveFile], manifest: dict, kind: str = "Full") -> list[ArchiveFile]:
    """Files that are new or whose ETag differs from the manifest (newest datestamp only)."""
    latest = max((f.datestamp for f in files), default="")
    todo: list[ArchiveFile] = []
    for f in files:
        if f.kind != kind or f.datestamp != latest:
            continue
        prev = manifest.get(logical_id(f))
        if prev is None or prev.get("etag") != f.etag:
            todo.append(f)
    return todo


def record(manifest: dict, f: ArchiveFile, *, rows: int, parquet_bytes: int, updated_at: str) -> None:
    """Upsert a manifest entry after a (product, FY, agency) has been published."""
    manifest[logical_id(f)] = {
        "etag": f.etag,
        "datestamp": f.datestamp,
        "rows": rows,
        "parquet_bytes": parquet_bytes,
        "parquet_key": parquet_key(f),
        "updated_at": updated_at,
    }
