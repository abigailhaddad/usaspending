"""compact_serve.reload_dedupe_select (2026-11-09), on rows shaped like the real cases."""
import duckdb

from usaspending_archive.compact_serve import reload_dedupe_select

COLS = "contract_award_unique_key, modification_number, action_date, federal_action_obligation, transaction_number, last_modified_date"


def _run(rows):
    con = duckdb.connect()
    con.execute("CREATE TABLE t (contract_award_unique_key VARCHAR, modification_number VARCHAR, action_date DATE,"
                " federal_action_obligation DOUBLE, transaction_number VARCHAR, last_modified_date DATE)")
    con.executemany(f"INSERT INTO t ({COLS}) VALUES (?, ?, ?, ?, ?, ?)", rows)
    return con.execute(f"SELECT transaction_number, federal_action_obligation FROM ({reload_dedupe_select('t')}) "
                       "ORDER BY transaction_number").fetchall()


RAY = "CONT_AWD_W31P4Q26C0001_9700_-NONE-_-NONE-"


def test_republished_copy_is_dropped():
    # Raytheon W31P4Q26C0001 mod 0: FPDS has one record; USASpending two.
    out = _run([(RAY, "0", "2026-03-04", 183682395.65, "0", "2026-03-04"),
                (RAY, "0", "2026-03-04", 183682395.65, "2", "2026-11-02")])
    assert out == [("0", 183682395.65)]


def test_order_does_not_matter():
    out = _run([(RAY, "0", "2026-03-04", 183682395.65, "2", "2026-11-02"),
                (RAY, "0", "2026-03-04", 183682395.65, "0", "2026-03-04")])
    assert out == [("0", 183682395.65)]


def test_older_pair_far_apart_is_kept_when_fpds_has_two():
    # H9240824C6972 P00010: FPDS transactions 14 and 16, both $51,092,377.83,
    # last modified 170 days apart -- both real, neither in a reload window.
    k = "CONT_AWD_H9240824C6972_9700_-NONE-_-NONE-"
    out = _run([(k, "P00010", "2025-02-18", 51092377.83, "14", "2025-02-18"),
                (k, "P00010", "2025-02-18", 51092377.83, "16", "2025-08-07")])
    assert len(out) == 2


def test_both_copies_inside_the_window_are_kept():
    out = _run([("K", "0", "2026-01-01", 9.0, "14", "2026-11-02"), ("K", "0", "2026-01-01", 9.0, "16", "2026-11-02")])
    assert len(out) == 2


def test_fpds_same_day_repeats_are_kept():
    # W31P4Q25F0043 mod 0: FPDS transactions 14 and 16, both $131,363,850.
    k = "CONT_AWD_W31P4Q25F0043_9700_W31P4Q19D0012_9700"
    out = _run([(k, "0", "2025-08-22", 131363850.0, "14", "2026-04-01"),
                (k, "0", "2025-08-22", 131363850.0, "16", "2026-04-02")])
    assert len(out) == 2


def test_different_amounts_under_one_mod_are_kept():
    # W31P4Q25C0007 mod 0: transaction 14 $7.00, transaction 16 $214,364,530.
    k = "CONT_AWD_W31P4Q25C0007_9700_-NONE-_-NONE-"
    out = _run([(k, "0", "2025-05-23", 7.0, "14", "2026-11-04"),
                (k, "0", "2025-05-23", 214364530.0, "16", "2026-11-04")])
    assert len(out) == 2


def test_same_day_pair_plus_republished_copies_keeps_the_pair():
    k = "K"
    rows = [(k, "0", "2025-08-22", 5.0, "16", "2026-11-04"), (k, "0", "2025-08-22", 5.0, "14", "2026-11-04"),
            (k, "0", "2025-08-22", 5.0, "14", "2026-04-01"), (k, "0", "2025-08-22", 5.0, "16", "2026-04-01")]
    assert len(_run(rows)) == 2


def test_lockheed_w31p4q25c0007_totals_to_fpds():
    k = "CONT_AWD_W31P4Q25C0007_9700_-NONE-_-NONE-"
    fpds = [("0", "2025-05-23", 214364530.0), ("0", "2025-05-23", 7.0), ("P00001", "2025-12-08", 16299990.93),
            ("P00001", "2025-12-08", 33699995.0), ("PZ0004", "2026-06-30", -36910783.0), ("PZ0005", "2026-07-17", 219222018.08)]
    rows = []
    for i, (m, d, a) in enumerate(fpds):
        rows.append((k, m, d, a, f"{i}a", "2026-07-20"))
        rows.append((k, m, d, a, f"{i}b", "2026-11-04"))
    assert round(sum(a for _, a in _run(rows)), 2) == 446675758.01


def test_module_constants_main_needs_are_defined():
    # 2026-11-09: the reload-window rewrite (#11) deleted these, and the first
    # rebuild died at startup with NameError: MANIFEST. main() reads all four.
    from usaspending_archive import compact_serve as cs
    assert cs.HF_REPO == "abigailhaddad/usaspending-bulk-awards"
    assert cs.MANIFEST.name == "manifest.json" and cs.MANIFEST.exists()
    assert cs.RESOLVE.startswith("https://huggingface.co/datasets/")
