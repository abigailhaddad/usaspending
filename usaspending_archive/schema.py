"""Column typing for archive CSVs.

We read every column as VARCHAR (no type sniffing — robust across 20 years of
schema drift), then TRY_CAST the columns we recognize as amounts/dates. TRY_CAST
turns a bad value into NULL instead of failing the whole file.

Typing rules are by column-name pattern (validated against the FY2024 Contracts
[297 cols] and Assistance [112 cols] headers):
  - ends with `_date`              -> DATE   (action_date, *_start_date, last_modified_date, ...)
  - ends with `_fiscal_year`       -> keep VARCHAR (it's a year, not a date; partition uses filename FY)
  - ends with `_code` / `_name` / `_description` -> VARCHAR, checked before
                                     the amount patterns (2026-11-09: the 20261106
                                     Assistance files added award_amount_basis_code
                                     and award_amount_basis_name -- 116 cols, up from
                                     112 -- whose "_amount" made them DOUBLE. Values
                                     like "A01" then failed the whole file under
                                     DuckDB 2.0; under 1.x TRY_CAST would have
                                     silently NULLed them.)
  - matches an amount pattern      -> DOUBLE (obligations, outlays, value_of_award, loan/subsidy, officer amounts)
  - everything else                -> VARCHAR
"""
from __future__ import annotations

_TEXT_SUFFIXES = ("_code", "_name", "_description")

_AMOUNT_PATTERNS = (
    "obligation", "_amount", "value_of_award", "outlayed_amount",
    "_outlay", "total_dollars", "face_value", "subsidy", "_funding_amount",
    "indirect_cost", "pragmatic_obligations",
)


def column_type(name: str) -> str:
    """Return the DuckDB target type for a column: DATE, DOUBLE, or VARCHAR."""
    if name.endswith("_fiscal_year"):
        return "VARCHAR"
    if name.endswith("_date"):
        return "DATE"
    if name.endswith(_TEXT_SUFFIXES):
        return "VARCHAR"
    if any(p in name for p in _AMOUNT_PATTERNS):
        return "DOUBLE"
    return "VARCHAR"


def select_expr(name: str) -> str:
    """A SQL select expression that casts the column to its target type.

    Column names can contain hyphens (e.g. COVID-19 columns), so identifiers are
    always double-quoted.
    """
    t = column_type(name)
    q = '"' + name.replace('"', '""') + '"'
    if t == "VARCHAR":
        return q
    return f'TRY_CAST({q} AS {t}) AS {q}'
