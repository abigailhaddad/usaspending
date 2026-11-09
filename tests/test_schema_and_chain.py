"""Offline tests for column typing and the backfill chain decision (2026-11-09)."""
import pytest

from usaspending_archive import schema
from usaspending_archive.backfill import _chain_decision


@pytest.mark.parametrize("col", ["award_amount_basis_code", "award_amount_basis_name"])
def test_new_assistance_text_columns_stay_varchar(col):
    # "_amount" in the name used to make these DOUBLE; values are like "A01".
    assert schema.column_type(col) == "VARCHAR"


@pytest.mark.parametrize("col", [
    "federal_action_obligation", "total_dollars_obligated", "face_value_of_loan",
    "total_outlayed_amount_for_overall_award", "original_loan_subsidy_cost",
    "obligated_amount_from_COVID-19_supplementals_for_overall_award",
])
def test_real_amounts_still_double(col):
    assert schema.column_type(col) == "DOUBLE"


def test_error_does_not_chain_and_fails(capsys):
    rc = _chain_decision(blocked=False, error=ValueError("Conversion Error"), done=0, remaining=452)
    assert rc == 1 and "CHAIN_NEEDED" not in capsys.readouterr().out


def test_ip_block_chains(capsys):
    assert _chain_decision(blocked=True, error=None, done=0, remaining=452) == 0
    assert "CHAIN_NEEDED" in capsys.readouterr().out


def test_progress_with_files_left_chains(capsys):
    assert _chain_decision(blocked=False, error=None, done=200, remaining=252) == 0
    assert "CHAIN_NEEDED" in capsys.readouterr().out


def test_no_progress_no_block_does_not_chain(capsys):
    assert _chain_decision(blocked=False, error=None, done=0, remaining=5) == 1
    assert "CHAIN_NEEDED" not in capsys.readouterr().out


def test_drained_no_chain(capsys):
    assert _chain_decision(blocked=False, error=None, done=3, remaining=0) == 0
    assert "CHAIN_NEEDED" not in capsys.readouterr().out
