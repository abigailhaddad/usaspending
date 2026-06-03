"""Tests for the table-builder SQL engine (site/api/query.py).

These pin the SQL the engine emits: group-by shape, metric expansion, the optional
two-period (A/B) comparison, and that the reproduce() snippet inlines the public
HuggingFace source. They run with no DuckDB/network — pure string construction.
"""
import pytest

import query


def _req(**kw):
    base = {"dataset": "contracts", "metric": "obligations", "rows": "state"}
    base.update(kw)
    return base


# ---- _mask ---------------------------------------------------------------

def test_mask_none_is_true():
    assert query._mask(None) == "TRUE"


def test_mask_builds_between_on_date_col():
    m = query._mask(("2024-01-01", "2024-12-31"))
    assert m == "TRY_CAST(action_date AS DATE) BETWEEN '2024-01-01' AND '2024-12-31'"


def test_mask_honors_alternate_date_col():
    m = query._mask(("2024-01-01", "2024-12-31"), "last_modified_date")
    assert m.startswith("TRY_CAST(last_modified_date AS DATE)")


def test_mask_rejects_bad_date():
    with pytest.raises(ValueError):
        query._mask(("2024-1-1", "not-a-date"))


# ---- build_sql -----------------------------------------------------------

def test_build_sql_rejects_unknown_dataset_and_metric():
    with pytest.raises(ValueError):
        query.build_sql(_req(dataset="nope"))
    with pytest.raises(ValueError):
        query.build_sql(_req(metric="nope"))


def test_build_sql_single_dim_single_metric():
    sql, binds = query.build_sql(_req())
    assert "recipient_state_code AS g0" in sql
    assert "GROUP BY recipient_state_code" in sql
    assert " AS a" in sql and " AS b" not in sql      # no period B
    assert "{src}" in sql                              # source left as a placeholder
    assert binds == []


def test_build_sql_single_period_filters_to_a():
    sql, _ = query.build_sql(_req(periodA=("2024-01-01", "2024-12-31")))
    assert "WHERE TRY_CAST(action_date AS DATE) BETWEEN '2024-01-01' AND '2024-12-31'" in sql
    assert " AS b" not in sql


def test_build_sql_two_periods_emit_a_and_b():
    sql, _ = query.build_sql(_req(periodA=("2024-01-01", "2024-12-31"),
                                  periodB=("2025-01-01", "2025-12-31")))
    assert " AS a" in sql and " AS b" in sql           # both period columns
    assert " OR " in sql                               # where matches either period


def test_build_sql_multi_dim_group_by():
    sql, _ = query.build_sql(_req(rows=["state", "naics"]))
    assert "recipient_state_code AS g0" in sql
    assert "naics_code AS g1" in sql


def test_build_sql_passes_through_filter_binds():
    sql, binds = query.build_sql(_req(
        filter_clauses=["recipient_state_code IN (?)"], filter_binds=["CA"]))
    assert "recipient_state_code IN (?)" in sql        # value stays a bound ?
    assert binds == ["CA"]


# ---- build_multi_sql -----------------------------------------------------

def test_build_multi_sql_joins_metrics():
    sql, binds, metrics, two = query.build_multi_sql(
        _req(metrics=["obligations", "transactions"]))
    assert metrics == ["obligations", "transactions"]
    assert two is False
    assert "FULL JOIN" in sql
    assert "IS NOT DISTINCT FROM" in sql               # null-safe group-key join
    assert '"obligations__a"' in sql and '"transactions__a"' in sql
    assert '__b"' not in sql                            # single period -> no b columns


def test_build_multi_sql_two_periods_add_b_columns():
    sql, _, _, two = query.build_multi_sql(
        _req(metrics=["obligations"], periodB=("2025-01-01", "2025-12-31"),
             periodA=("2024-01-01", "2024-12-31")))
    assert two is True
    assert '"obligations__b"' in sql


def test_build_multi_sql_limit_is_int_coerced():
    # limit goes through int() so it can't carry SQL; assert the literal lands clean
    sql, _, _, _ = query.build_multi_sql(_req(metrics=["obligations"], limit="25"))
    assert sql.rstrip().endswith("LIMIT 25")


# ---- build_detail_sql ----------------------------------------------------

def test_build_detail_sql_uses_dataset_columns():
    sql, binds, cols = query.build_detail_sql(_req(dataset="assistance"))
    assert "award_id_fain" in cols                      # assistance-specific column
    assert "award_id_fain" in sql
    assert "LIMIT" in sql


# ---- reproduce -----------------------------------------------------------

def test_reproduce_inlines_public_source():
    out = query.reproduce(_req(periodA=("2024-01-01", "2024-12-31")))
    assert "python" in out and "sql" in out
    assert "hf://datasets/abigailhaddad/usaspending-bulk-awards" in out["python"]
    assert f"duckdb=={query.DUCKDB_VERSION}" in out["python"]
    assert "{src}" not in out["python"]                 # placeholder fully resolved


def test_reproduce_inlines_filter_binds_safely():
    # a value with a quote must be escaped, not break out of the string literal
    out = query.reproduce(_req(
        filter_clauses=["recipient_name IN (?)"], filter_binds=["O'Brien LLC"]))
    assert "'O''Brien LLC'" in out["sql"]
    assert "?" not in out["sql"]                         # every bind inlined
