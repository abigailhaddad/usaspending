"""backfill must not signal CHAIN_NEEDED forever for files that 404."""
import sys
from pathlib import Path
from unittest import mock

from usaspending_archive import backfill
from usaspending_archive.archive_index import ArchiveFile
from usaspending_archive.fetch import NOT_FOUND


def _f(agency):
    return ArchiveFile(key=f"FY2026_{agency}_Contracts_Full_20260506.zip", size=1,
                       etag="e" + agency, fiscal_year="2026", agency_code=agency,
                       award_type="Contracts", kind="Full", datestamp="20260506")


def _run(files, download, tmp_path, monkeypatch, capsys, max_files):
    monkeypatch.setenv("HF_TOKEN", "x")
    monkeypatch.setattr(backfill, "MANIFEST", tmp_path / "m.json")
    monkeypatch.setattr(sys, "argv", ["backfill", "--max-files", str(max_files), "--fiscal-years", "2026"])
    fake_hf = mock.MagicMock()
    with mock.patch.dict(sys.modules, {"huggingface_hub": mock.MagicMock(HfApi=fake_hf)}), \
         mock.patch.object(backfill, "list_archive", return_value=files), \
         mock.patch.object(backfill, "download_zip", side_effect=download), \
         mock.patch.object(backfill, "extract_csvs", return_value=[]), \
         mock.patch.object(backfill, "csv_to_parquet", return_value={"rows": 1, "bytes": 1}), \
         mock.patch.object(backfill, "publish_to_hf"):
        backfill.main()
    return capsys.readouterr().out


def test_all_not_found_does_not_chain(tmp_path, monkeypatch, capsys):
    files = [_f("001"), _f("002")]
    out = _run(files, lambda url: NOT_FOUND, tmp_path, monkeypatch, capsys, 10)
    assert "CHAIN_NEEDED" not in out


def test_not_found_does_not_consume_slice(tmp_path, monkeypatch, capsys):
    files = [_f("001"), _f("002"), _f("003")]
    dead = {files[0].url, files[1].url}

    def dl(url):
        if url in dead:
            return NOT_FOUND
        p = tmp_path / "z.zip"
        p.write_bytes(b"")
        return p
    out = _run(files, dl, tmp_path, monkeypatch, capsys, 1)
    assert "processed 1, 0 changed files remain" in out
    assert "CHAIN_NEEDED" not in out


def test_ip_block_chain_is_capped():
    """2026-11-10: a block that never lifts must not chain forever. Blocked hops that
    land nothing chain up to MAX_STALLED_HOPS in a row; the next one stops and fails."""
    d = backfill._chain_decision
    cap = backfill.MAX_STALLED_HOPS
    assert d(blocked=True, error=None, done=0, remaining=5, stalled_hops=cap - 1) == 0  # last allowed
    assert d(blocked=True, error=None, done=0, remaining=5, stalled_hops=cap) == 1      # one too many
    # progress resets nothing here: a blocked hop that landed files always chains
    assert d(blocked=True, error=None, done=3, remaining=5, stalled_hops=cap + 5) == 0
