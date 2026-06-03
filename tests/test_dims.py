"""Tests for the dimension/metric/filter registry (site/api/dims.py).

The registry is the allowlist that keeps the table builder injection-safe: dimension
and filter *keys* map to vetted column SQL, and all user *values* are bound parameters.
These tests pin that contract.
"""
import dims


def test_resolve_col_known_dimension():
    # a curated dimension resolves to its declared column expression
    assert dims.resolve_col("state") == "recipient_state_code"
    assert dims.resolve_col("awarding_agency") == "awarding_agency_name"


def test_resolve_col_alias():
    # friendly aliases map to the real raw column
    assert dims.resolve_col("psc_code") == "product_or_service_code"
    assert dims.resolve_col("funding_subagency_code") == "funding_sub_agency_code"


def test_resolve_col_arbitrary_identifier_is_quoted():
    # any bare-identifier raw column is allowed but quoted, never interpolated raw
    assert dims.resolve_col("recipient_uei") == '"recipient_uei"'


def test_resolve_col_rejects_injection():
    # anything that isn't a known key/alias or a safe identifier is refused
    assert dims.resolve_col("a; DROP TABLE x") is None
    assert dims.resolve_col("state code") is None          # space
    assert dims.resolve_col("col')--") is None             # quote/comment
    assert dims.resolve_col("") is None


def test_resolve_date_col_allowlist():
    assert dims.resolve_date_col("period_of_performance_start_date") == "period_of_performance_start_date"
    # unknown / injection falls back to the default date column, never echoes input
    assert dims.resolve_date_col("evil; --") == dims.DATE_COL
    assert dims.resolve_date_col(None) == dims.DATE_COL


def test_parse_filters_in_clause_splits_and_binds():
    clauses, binds = dims.parse_filters({"filter_state": ["CA|NY|TX"]})
    assert clauses == ["recipient_state_code IN (?,?,?)"]
    assert binds == ["CA", "NY", "TX"]


def test_parse_filters_range_casts_to_float():
    clauses, binds = dims.parse_filters({"filter_obligations_min": ["100"],
                                         "filter_obligations_max": ["500"]})
    assert any(">= ?" in c for c in clauses)
    assert any("<= ?" in c for c in clauses)
    assert binds == [100.0, 500.0]


def test_parse_filters_ignores_non_filter_and_empty():
    # keys without the filter_ prefix are skipped; empty values produce no clause
    clauses, binds = dims.parse_filters({"rows": ["state"], "filter_state": [""]})
    assert clauses == []
    assert binds == []


def test_parse_filters_drops_uninjectable_field():
    # an unsafe field name resolves to None -> no clause, value never reaches SQL
    clauses, binds = dims.parse_filters({"filter_a; DROP": ["x"]})
    assert clauses == []
    assert binds == []
