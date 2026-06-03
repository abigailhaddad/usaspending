"""Integration tests for the table-builder execution path (site/api/table.py).

The query.py tests prove the SQL is *shaped* right; these prove it *runs* and that the
response math is right. They point DuckDB at a tiny committed CSV fixture via
USP_SOURCE_TMPL (the same hook prod uses for local/HF/R2), so there's no network, no
HF/R2 — just real DuckDB aggregation over six contract rows + three assistance rows.

Fixture (contracts), periods A=2024, B=2025:
  CA: A = 100+200 = 300, B = 50   -> Δ = -250, Δ% = -83.3
  NY: A = 300,           B = 70
  TX: A = 0,             B = none (no 2025 row)
"""
import os

import pytest

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")


@pytest.fixture(autouse=True)
def _local_source(monkeypatch):
    # read_csv with all_varchar=true mirrors the production varchar parquet, so the
    # TRY_CAST()s in the SQL are exercised exactly as they are against the real data.
    monkeypatch.setenv(
        "USP_SOURCE_TMPL",
        f"read_csv('{FIXTURES}/{{dataset}}/part.csv', all_varchar=true)")


import table  # noqa: E402  (conftest puts site/api on the path; env hook is read at call time)


def _params(**kw):
    """Mimic urllib.parse.parse_qs output: every value is a list of strings."""
    return {k: (v if isinstance(v, list) else [v]) for k, v in kw.items()}


def _row(tbl, key):
    """The single data row whose first cell equals `key`."""
    return next(r for r in tbl["data"] if r[0] == key)


A_2024 = "2024-01-01..2024-12-31"
B_2025 = "2025-01-01..2025-12-31"


# ---- single-period aggregation ------------------------------------------

def test_single_period_obligation_sums():
    res = table.build_response(_params(
        dataset="contracts", rows="state", metric="obligations", periodA=A_2024))
    tbl = res["tables"][0]
    assert tbl["columns"] == ["Recipient state", "Obligations ($)"]
    assert _row(tbl, "CA")[1] == 300
    assert _row(tbl, "NY")[1] == 300
    assert _row(tbl, "TX")[1] == 0          # zero obligation aggregates to 0, not null


def test_multi_metric_columns_and_counts():
    res = table.build_response(_params(
        dataset="contracts", rows="state", metric="obligations,transactions", periodA=A_2024))
    tbl = res["tables"][0]
    assert tbl["columns"] == ["Recipient state", "Obligations ($)", "Transactions"]
    assert _row(tbl, "CA") == ["CA", 300, 2]   # two 2024 CA transactions


def test_multi_dimension_group_by():
    res = table.build_response(_params(
        dataset="contracts", rows="state,business_size", metric="obligations", periodA=A_2024))
    tbl = res["tables"][0]
    assert tbl["group_cols"] == 2
    assert tbl["columns"][:2] == ["Recipient state", "Business size"]


def test_filter_narrows_results():
    res = table.build_response(_params(
        dataset="contracts", rows="state", metric="obligations",
        periodA=A_2024, filter_state="CA"))
    tbl = res["tables"][0]
    assert {r[0] for r in tbl["data"]} == {"CA"}
    assert _row(tbl, "CA")[1] == 300


# ---- two-period comparison math (the part with zero prior coverage) ------

def test_two_period_delta_and_pct():
    res = table.build_response(_params(
        dataset="contracts", rows="state", metric="obligations",
        periodA=A_2024, periodB=B_2025))
    tbl = res["tables"][0]
    assert tbl["columns"] == [
        "Recipient state", "Obligations ($) — A", "Obligations ($) — B",
        "Obligations ($) — Δ", "Obligations ($) — Δ%"]
    assert _row(tbl, "CA")[1:] == [300, 50, -250, -83.3]
    assert _row(tbl, "NY")[1:] == [300, 70, -230, -76.7]


def test_two_period_missing_b_is_null():
    res = table.build_response(_params(
        dataset="contracts", rows="state", metric="obligations",
        periodA=A_2024, periodB=B_2025))
    tx = _row(res["tables"][0], "TX")
    # TX has no 2025 row: A=0, B/Δ/Δ% all null (no divide-by-zero, no fabricated delta)
    assert tx[1] == 0
    assert tx[2] is None and tx[3] is None and tx[4] is None


# ---- detail (record-level) ----------------------------------------------

def test_detail_returns_dataset_columns_and_all_rows():
    from dims import DETAIL_COLUMNS
    res = table.detail_response(_params(dataset="contracts"))
    assert res["columns"] == DETAIL_COLUMNS["contracts"]
    assert res["count"] == 6
    assert res["truncated"] is False


def test_detail_period_filters_rows():
    res = table.detail_response(_params(dataset="contracts", periodA=A_2024))
    assert res["count"] == 4          # four contract rows dated in FY2024 window


def test_detail_limit_sets_truncated_flag():
    res = table.detail_response(_params(dataset="contracts", limit="2"))
    assert res["count"] == 2
    assert res["truncated"] is True


# ---- fields + assistance dataset ----------------------------------------

def test_fields_lists_columns_without_partition_virtuals():
    res = table.fields_response(_params(dataset="contracts"))
    vals = {f["value"] for f in res["fields"]}
    assert {"federal_action_obligation", "recipient_state_code"} <= vals
    assert "fiscal_year" not in vals and "agency" not in vals


def test_assistance_detail_uses_fain_columns():
    res = table.detail_response(_params(dataset="assistance"))
    assert "award_id_fain" in res["columns"]
    assert "cfda_number" in res["columns"]
    assert res["count"] == 3
