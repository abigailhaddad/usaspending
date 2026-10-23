"""Offline tests for backfill.py's exit status + chaining (no network/creds).

Everything that touches the network (archive listing, zip download, HF) is
monkeypatched on the backfill module, so these exercise the real main() loop.
"""
from pathlib import Path

import pytest

from usaspending_archive import backfill, manifest
from usaspending_archive.archive_index import ArchiveFile
from usaspending_archive.fetch import FAILED, IP_BLOCKED, NOT_FOUND


def _f(agency, fy="2026", etag="e"):
    return ArchiveFile(
        key=f"FY{fy}_{agency}_Contracts_Full_20261006.zip", size=1, etag=etag,
        fiscal_year=fy, agency_code=agency, award_type="Contracts", kind="Full",
        datestamp="20261006",
    )


class _FakeApi:
    def __init__(self, token=None):
        pass

    def create_repo(self, *a, **k):
        pass


@pytest.fixture
def run(monkeypatch, tmp_path):
    """Return a runner: run(files, outcomes, argv) -> (exit code, stdout, published keys).

    outcomes maps agency code -> a fetch sentinel (IP_BLOCKED/NOT_FOUND/FAILED),
    "convert_error", or absent for success.
    """
    import huggingface_hub

    monkeypatch.setenv("HF_TOKEN", "test-not-a-token")
    monkeypatch.setattr(huggingface_hub, "HfApi", _FakeApi)
    monkeypatch.setattr(backfill, "MANIFEST", tmp_path / "manifest.json")
    published: list[str] = []

    def go(files, outcomes=None, argv=(), publish_raises=False):
        outcomes = outcomes or {}
        by_url = {f.url: f for f in files}
        monkeypatch.setattr(backfill, "list_archive", lambda: list(files))

        def fake_download(url):
            o = outcomes.get(by_url[url].agency_code)
            if o in (IP_BLOCKED, NOT_FOUND, FAILED):
                return o
            p = tmp_path / (by_url[url].agency_code + ".zip")
            p.write_bytes(b"zip")
            return p

        def fake_extract(zp, dest):
            if outcomes.get(Path(zp).stem) == "convert_error":
                raise ValueError("bad zip")
            return []

        def fake_publish(pairs, repo, batch_size):
            if publish_raises:
                raise RuntimeError("HTTP 429")
            published.extend(k for _, k in pairs)

        monkeypatch.setattr(backfill, "download_zip", fake_download)
        monkeypatch.setattr(backfill, "extract_csvs", fake_extract)
        monkeypatch.setattr(backfill, "csv_to_parquet",
                            lambda csvs, out, con: {"rows": 10, "bytes": 100})
        monkeypatch.setattr(backfill, "publish_to_hf", fake_publish)
        published.clear()
        rc = backfill.main(["--fiscal-years", "2026", *argv])
        return rc, list(published)

    return go


# ---- main(): exit status -------------------------------------------------------------

def test_clean_drain_exits_zero_no_chain(run, capsys):
    rc, pub = run([_f("097"), _f("012")])
    out = capsys.readouterr().out
    assert rc == 0 and len(pub) == 2
    assert "CHAIN_NEEDED" not in out
    assert "processed 2, 0 changed files remain" in out


@pytest.mark.parametrize("sentinel", [NOT_FOUND, FAILED, "convert_error"])
def test_non_ip_failure_exits_nonzero_but_others_still_publish(run, capsys, sentinel):
    rc, pub = run([_f("097"), _f("012")], {"097": sentinel})
    out = capsys.readouterr().out
    assert rc == 1
    assert pub == ["contracts/fiscal_year=2026/agency=012/part.parquet"]
    assert "FAILED: 1 error(s)" in out and "FY2026_097" in out
    # progress was made, so one more hop is allowed to retry the failed file
    assert "CHAIN_NEEDED" in out


def test_only_failing_files_left_stops_chaining(run, capsys):
    # The re-chain-forever case: a permanently failing file and nothing else.
    rc, pub = run([_f("097")], {"097": NOT_FOUND})
    out = capsys.readouterr().out
    assert rc == 1 and pub == []
    assert "CHAIN_NEEDED" not in out
    assert "drain stranded" in out


def test_publish_exception_exits_nonzero_no_chain(run, capsys):
    rc, pub = run([_f("097")], publish_raises=True)
    out = capsys.readouterr().out
    assert rc == 1
    assert "unexpected error: HTTP 429" in out
    assert "CHAIN_NEEDED" not in out


def test_manifest_not_recorded_for_failed_file(run, capsys):
    run([_f("097"), _f("012")], {"097": FAILED})
    m = manifest.load(backfill.MANIFEST)
    assert "contracts/2026/012" in m and "contracts/2026/097" not in m


# ---- main(): IP-block self-chaining still works --------------------------------------

def test_ip_block_after_progress_chains_and_exits_zero(run, capsys):
    rc, pub = run([_f("097", etag="a"), _f("012", etag="b")], {"012": IP_BLOCKED})
    out = capsys.readouterr().out
    assert rc == 0 and len(pub) == 1
    assert "CHAIN_NEEDED" in out


def test_ip_block_with_no_progress_chains_until_cap(run, capsys):
    rc, _ = run([_f("097")], {"097": IP_BLOCKED}, argv=["--stalled-hops", "0"])
    assert rc == 0 and "CHAIN_NEEDED" in capsys.readouterr().out
    rc, _ = run([_f("097")], {"097": IP_BLOCKED}, argv=["--stalled-hops", "2"])
    assert rc == 0 and "CHAIN_NEEDED" in capsys.readouterr().out  # 3rd stalled hop: ok
    rc, _ = run([_f("097")], {"097": IP_BLOCKED}, argv=["--stalled-hops", "3"])
    out = capsys.readouterr().out
    assert rc == 1 and "CHAIN_NEEDED" not in out  # 4th: refused, loudly
    assert "consecutive hops" in out


# ---- chain_decision() ----------------------------------------------------------------

@pytest.mark.parametrize("kw,expect", [
    (dict(blocked=False, done=5, remaining=0), False),   # drained
    (dict(blocked=False, done=5, remaining=3), True),    # progress, more to do
    (dict(blocked=True, done=5, remaining=3), True),     # progress then blocked
    (dict(blocked=False, done=0, remaining=3), False),   # stuck on own failures
    (dict(blocked=True, done=0, remaining=3), True),     # blocked, under cap
])
def test_chain_decision(kw, expect):
    chain, reason = backfill.chain_decision(stalled_hops=0, max_stalled_hops=3, **kw)
    assert chain is expect and reason


def test_chain_decision_cap_is_consecutive_stalls_not_total_hops():
    assert backfill.chain_decision(blocked=True, done=0, remaining=9,
                                   stalled_hops=3, max_stalled_hops=3)[0] is False
    # any progress resets: a long legitimate re-ingest keeps chaining
    assert backfill.chain_decision(blocked=True, done=1, remaining=9,
                                   stalled_hops=99, max_stalled_hops=3)[0] is True
