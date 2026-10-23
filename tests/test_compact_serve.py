"""Offline tests for compact_serve's replace-guard (no network/creds).

Builds small parquet files with DuckDB and points the "current serve file" URL at a
local directory, so the footer-metadata path runs exactly as it does over https.
"""
import datetime as dt

import duckdb
import pytest

from usaspending_archive import compact_serve as cs


def _write(path, rows, start="2025-10-01", end="2026-09-30", drop_col=None, extra_col=False):
    con = duckdb.connect()
    cols = ["i AS id", "'x' AS recipient_name",
            f"DATE '{start}' + CAST(floor((i * (DATE '{end}' - DATE '{start}')) / "
            f"greatest({rows} - 1, 1)) AS INTEGER) AS action_date"]
    if extra_col:
        cols.append("1 AS new_col")
    cols = [c for c in cols if not (drop_col and c.endswith(f" AS {drop_col}"))]
    path.parent.mkdir(parents=True, exist_ok=True)
    con.execute(f"COPY (SELECT {', '.join(cols)} FROM range({rows}) t(i)) TO '{path}' "
                f"(FORMAT parquet, ROW_GROUP_SIZE 100)")
    return path


def test_parquet_summary_matches_exact_scan(tmp_path):
    p = _write(tmp_path / "a.parquet", 1000)
    s = cs.parquet_summary(duckdb.connect(), str(p))
    exact = duckdb.connect().execute(
        f"SELECT count(*), min(action_date), max(action_date) FROM read_parquet('{p}')").fetchone()
    assert (s["rows"], s["min_date"], s["max_date"]) == exact
    assert s["max_date"] == dt.date(2026, 9, 30)
    assert s["columns"] == ["id", "recipient_name", "action_date"]


def test_parquet_summary_without_action_date(tmp_path):
    p = _write(tmp_path / "a.parquet", 10, drop_col="action_date")
    s = cs.parquet_summary(duckdb.connect(), str(p))
    assert s["min_date"] is None and s["max_date"] is None


def _s(rows=1000, cols=("a", "b", "action_date"), lo="2025-10-01", hi="2026-09-30"):
    return {"rows": rows, "columns": list(cols),
            "min_date": dt.date.fromisoformat(lo) if lo else None,
            "max_date": dt.date.fromisoformat(hi) if hi else None}


@pytest.mark.parametrize("new,n_problems", [
    (_s(), 0),                                     # identical
    (_s(rows=951), 0),                             # -4.9%: within tolerance
    (_s(rows=2000, cols=("a", "b", "action_date", "c")), 0),  # growth + added col ok
    (_s(rows=949), 1),                             # -5.1%
    (_s(cols=("a", "action_date")), 1),            # column removed
    (_s(cols=("a", "B", "action_date")), 1),       # column renamed
    (_s(hi="2026-08-31"), 1),                      # max date went backwards
    (_s(lo="2025-11-01"), 1),                      # min date moved later
    (_s(lo=None, hi=None, cols=("a", "b")), 2),    # date col gone: missing col + range lost
])
def test_compare_serve(new, n_problems):
    assert len(cs.compare_serve(_s(), new)) == n_problems


class _FakeApi:
    def __init__(self, exists):
        self.exists = exists

    def file_exists(self, repo_id, path, repo_type=None):
        return self.exists


@pytest.fixture
def live(tmp_path, monkeypatch):
    """Put a 'current' serve/contracts/2026.parquet under a local RESOLVE root."""
    root = tmp_path / "hf"
    _write(root / "serve" / "contracts" / "2026.parquet", 1000)
    monkeypatch.setattr(cs, "RESOLVE", str(root) + "/")
    return tmp_path


def test_check_refuses_shrunken_file(live, capsys):
    new = _write(live / "new.parquet", 900, end="2026-08-31")
    ok = cs.check_before_replace(duckdb.connect(), _FakeApi(True), "contracts", "2026",
                                 new, allow_shrink=False)
    out = capsys.readouterr().out
    assert ok is False
    assert "REFUSED" in out and "rows dropped 1,000 -> 900" in out
    assert "max(action_date) went backwards 2026-09-30 -> 2026-08-31" in out


def test_check_override_allows_shrunken_file(live, capsys):
    new = _write(live / "new.parquet", 900)
    assert cs.check_before_replace(duckdb.connect(), _FakeApi(True), "contracts", "2026",
                                   new, allow_shrink=True) is True
    assert "uploading anyway" in capsys.readouterr().out


def test_check_allows_normal_growth(live, capsys):
    new = _write(live / "new.parquet", 1010, extra_col=True)
    assert cs.check_before_replace(duckdb.connect(), _FakeApi(True), "contracts", "2026",
                                   new, allow_shrink=False) is True
    assert "rows 1,000 -> 1,010" in capsys.readouterr().out


def test_check_first_publish_skips_compare(tmp_path, monkeypatch):
    monkeypatch.setattr(cs, "RESOLVE", str(tmp_path / "nothing-here") + "/")
    new = _write(tmp_path / "new.parquet", 5)
    assert cs.check_before_replace(duckdb.connect(), _FakeApi(False), "contracts", "2026",
                                   new, allow_shrink=False) is True


@pytest.mark.parametrize("v,expect", [("1", True), ("true", True), ("YES", True),
                                      ("false", False), ("", False), (None, False)])
def test_truthy(v, expect):
    assert cs._truthy(v) is expect


def test_parquet_summary_scans_when_stats_missing(tmp_path):
    # A writer that omits row-group stats must not silently disable the date check.
    import pyarrow as pa
    import pyarrow.parquet as pq
    p = tmp_path / "nostats.parquet"
    pq.write_table(pa.table({"action_date": [dt.date(2025, 10, 3), dt.date(2026, 9, 1)]}),
                   p, write_statistics=False)
    con = duckdb.connect()
    assert con.execute("SELECT count(stats_max_value) FROM parquet_metadata(?)",
                       [str(p)]).fetchone()[0] == 0
    s = cs.parquet_summary(con, str(p))
    assert (s["min_date"], s["max_date"]) == (dt.date(2025, 10, 3), dt.date(2026, 9, 1))
