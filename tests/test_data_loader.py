"""Pins the httpfs gate in data_loader (site/api/data_loader.py).

get_conn() skips `INSTALL httpfs` for local file sources so the offline integration
suite (and dev) needs no network — but it MUST still install for the real remote
sources (default HF, r2://). These tests guard that production direction.
"""
import data_loader


def test_remote_sources_need_httpfs():
    assert data_loader._needs_httpfs("read_parquet('hf://datasets/x/*.parquet')") is True
    assert data_loader._needs_httpfs("read_parquet('r2://bucket/serve/*.parquet')") is True
    assert data_loader._needs_httpfs("read_parquet('s3://bucket/*.parquet')") is True


def test_local_source_skips_httpfs():
    assert data_loader._needs_httpfs("read_csv('/tmp/contracts/part.csv')") is False


def test_default_no_env_is_remote(monkeypatch):
    # no USP_SOURCE_TMPL -> falls back to the public HF dataset, which needs httpfs
    monkeypatch.delenv("USP_SOURCE_TMPL", raising=False)
    assert data_loader._needs_httpfs(None) is True


def test_env_template_detected_when_source_unknown(monkeypatch):
    monkeypatch.setenv("USP_SOURCE_TMPL", "read_csv('/data/{dataset}/*.csv', all_varchar=true)")
    assert data_loader._needs_httpfs(None) is False
    monkeypatch.setenv("USP_SOURCE_TMPL", "read_parquet('hf://datasets/x/{dataset}/*.parquet')")
    assert data_loader._needs_httpfs(None) is True
