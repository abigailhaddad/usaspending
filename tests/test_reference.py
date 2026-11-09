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


def test_empty_table_is_a_failure_and_is_not_uploaded(monkeypatch, tmp_path):
    import sys
    import types
    from usaspending_archive import reference_data as rd

    uploaded = []

    class FakeApi:
        def __init__(self, **kw): pass
        def upload_file(self, path_or_fileobj, path_in_repo, **kw):
            uploaded.append(path_in_repo)

    monkeypatch.setenv("HF_TOKEN", "x")
    monkeypatch.setitem(sys.modules, "huggingface_hub", types.SimpleNamespace(HfApi=FakeApi))
    monkeypatch.setattr(rd, "OUT", tmp_path)
    monkeypatch.setattr(rd, "ROOT", tmp_path)
    monkeypatch.setattr(rd, "SPECS", {"good": lambda: [{"a": 1}], "empty": lambda: []})
    (tmp_path / "stale.parquet").write_bytes(b"leftover")   # not from this run

    assert rd.snapshot_all() == ["empty"]
    assert uploaded == ["reference/good.parquet"]
