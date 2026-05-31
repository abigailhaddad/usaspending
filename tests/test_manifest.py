"""Offline tests for ETag change-detection + publish helpers (no network/creds)."""
from pathlib import Path

from usaspending_archive.archive_index import ArchiveFile
from usaspending_archive import manifest, publish


def _f(product, fy, agency, etag, datestamp="20260506", kind="Full"):
    return ArchiveFile(
        key=f"FY{fy}_{agency}_{product}_{kind}_{datestamp}.zip",
        size=100, etag=etag, fiscal_year=fy, agency_code=agency,
        award_type=product, kind=kind, datestamp=datestamp,
    )


def test_logical_id_and_parquet_key():
    f = _f("Contracts", "2024", "097", "abc")
    assert manifest.logical_id(f) == "contracts/2024/097"
    assert manifest.parquet_key(f) == "contracts/fiscal_year=2024/agency=097/part.parquet"


def test_changed_detects_new_and_modified_skips_unchanged():
    files = [
        _f("Contracts", "2024", "097", "etag-A"),   # new
        _f("Assistance", "2024", "012", "etag-B"),   # unchanged
        _f("Contracts", "2023", "097", "etag-NEW"),  # etag changed
    ]
    m = {
        "assistance/2024/012": {"etag": "etag-B"},
        "contracts/2023/097": {"etag": "etag-OLD"},
    }
    todo = {manifest.logical_id(f) for f in manifest.changed(files, m)}
    assert todo == {"contracts/2024/097", "contracts/2023/097"}


def test_changed_only_latest_datestamp_and_full():
    files = [
        _f("Contracts", "2024", "097", "x", datestamp="20260506"),  # latest -> in
        _f("Contracts", "2024", "097", "x", datestamp="20260406"),  # stale datestamp -> out
        _f("Contracts", "2024", "097", "x", kind="Delta"),          # delta -> out
    ]
    todo = manifest.changed(files, {})
    assert len(todo) == 1 and todo[0].datestamp == "20260506" and todo[0].kind == "Full"


def test_record_roundtrip(tmp_path):
    m = {}
    f = _f("Contracts", "2024", "097", "etag-A")
    manifest.record(m, f, rows=42, parquet_bytes=999, updated_at="2026-05-30T00:00:00Z")
    p = tmp_path / "manifest.json"
    manifest.save(p, m)
    back = manifest.load(p)
    assert back["contracts/2024/097"]["etag"] == "etag-A"
    assert back["contracts/2024/097"]["rows"] == 42
    # an unchanged re-list now skips it
    assert manifest.changed([f], back) == []


def test_iter_tree_keys(tmp_path):
    p = tmp_path / "contracts" / "fiscal_year=2024" / "agency=097" / "part.parquet"
    p.parent.mkdir(parents=True)
    p.write_bytes(b"x")
    files = publish.iter_tree(tmp_path)
    assert files == [(p, "contracts/fiscal_year=2024/agency=097/part.parquet")]
