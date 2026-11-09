"""backfill.main: a file that cannot be fetched or converted must not keep the drain
chaining forever, and must not discard the files that did convert."""
import sys
import types
from pathlib import Path

import pytest

from usaspending_archive import backfill, manifest
from usaspending_archive.archive_index import ArchiveFile
from usaspending_archive.fetch import NOT_FOUND


def _file(agency):
    return ArchiveFile(key=f"FY2026_{agency}_Contracts_Full_20261101.zip", size=1,
                       etag=f"e{agency}", fiscal_year="2026", agency_code=agency,
                       award_type="Contracts", kind="Full", datestamp="20261101")


@pytest.fixture
def run(monkeypatch, tmp_path, capsys):
    published = []

    class FakeApi:
        def __init__(self, **kw): pass
        def create_repo(self, *a, **k): pass

    monkeypatch.setenv("HF_TOKEN", "x")
    monkeypatch.setitem(sys.modules, "huggingface_hub",
                        types.SimpleNamespace(HfApi=FakeApi))
    monkeypatch.setattr(backfill, "MANIFEST", tmp_path / "manifest.json")
    monkeypatch.setattr(sys, "argv", ["backfill"])
    monkeypatch.setattr(backfill, "publish_to_hf",
                        lambda files, repo, batch_size=0: published.extend(k for _, k in files))
    monkeypatch.setattr(backfill, "extract_csvs", lambda zp, dest: [])

    def go(files, downloads, convert=None):
        monkeypatch.setattr(backfill, "list_archive", lambda: files)
        monkeypatch.setattr(backfill, "download_zip",
                            lambda url: downloads[url.rsplit("/", 1)[1].split("_")[1]](tmp_path))

        def fake_convert(csvs, out, con):
            if convert:
                convert(out)
            out.write_bytes(b"x")
            return {"rows": 1, "bytes": 1}
        monkeypatch.setattr(backfill, "csv_to_parquet", fake_convert)
        backfill.main()
        return capsys.readouterr().out, published
    return go


def _zip(tmp, name):
    p = tmp / f"{name}.zip"
    p.write_bytes(b"z")
    return p


def test_not_found_file_does_not_chain_forever(run):
    out, published = run([_file("001"), _file("002")],
                         {"001": lambda t: NOT_FOUND, "002": lambda t: _zip(t, "b")})
    assert "CHAIN_NEEDED" not in out
    assert len(published) == 1 and "agency=002" in published[0]


def test_one_unconvertible_zip_does_not_discard_the_rest(run):
    def boom(out):
        if "001" in str(out):
            raise ValueError("Not a zip file")
    out, published = run([_file("001"), _file("002")],
                         {"001": lambda t: _zip(t, "a"), "002": lambda t: _zip(t, "b")},
                         convert=boom)
    assert "CHAIN_NEEDED" not in out
    assert len(published) == 1 and "agency=002" in published[0]
