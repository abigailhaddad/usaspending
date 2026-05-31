"""Offline tests for data-dictionary parsing (the duplicate-header / trailing-null quirks)."""
from usaspending_archive.reference_data import dd_columns, parse_data_dictionary

# Mirrors the live shape: 17 headers with repeats, rows 18 long w/ a trailing null.
HEADERS = [
    {"raw": "A:element", "display": "Element"},
    {"raw": "B:definition", "display": "Definition"},
    {"raw": "G:award_file", "display": "Award File"},
    {"raw": "N:element", "display": "Element"},        # duplicate display
    {"raw": "O:award_file", "display": "Award File"},   # duplicate display
]
DOC = {
    "headers": HEADERS,
    "rows": [["el1", "def1", "Contracts.csv", "raw_el1", "Contracts", None]],  # 6 long, 5 headers
}


def test_dd_columns_dedupes_by_raw_letter():
    assert dd_columns(HEADERS) == [
        "Element", "Definition", "Award File", "Element (N)", "Award File (O)"
    ]


def test_parse_keeps_both_sections_and_drops_trailing():
    row = parse_data_dictionary(DOC)[0]
    assert row["Element"] == "el1"            # first-section value preserved...
    assert row["Element (N)"] == "raw_el1"    # ...not overwritten by the second section
    assert row["Award File"] == "Contracts.csv"
    assert row["Award File (O)"] == "Contracts"
    assert "None" not in row and len(row) == 5  # trailing null column dropped
