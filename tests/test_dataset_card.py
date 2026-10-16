"""Offline tests for the generated HF dataset card.

2026-10-16: the raw hive tree has an `agency=All` partition per fiscal year that is a
complete second copy of that year's per-agency partitions, so an unfiltered glob over
`contracts/**` double-counts (a FY2024-26 query came out at exactly 2.00x serve/ and
the USAspending API). The card must say so, and no example may glob the raw tree
without an agency predicate.
"""
import re

from usaspending_archive.dataset_card import generate

CARD = generate()

# Every SQL string in the card's examples (they're all ''' ... ''' blocks).
SQL_BLOCKS = re.findall(r"'''(.*?)'''", CARD, flags=re.S)

# A read over the raw hive tree (not serve/ or reference/).
RAW_READ = re.compile(r"read_parquet\(\s*'(?:hf://datasets/[^/']+/[^/']+/)?(contracts|assistance)/", re.I)
AGENCY_PRED = re.compile(r"\bagency\s*(?:=|!=|<>|in\b)", re.I)


def test_card_warns_that_agency_all_duplicates():
    assert "`agency=All` is a duplicate" in CARD
    assert "never combine it with the other agency partitions" in CARD
    assert "agency != 'All'" in CARD
    assert "agency = 'All'" in CARD
    assert "twice" in CARD
    assert "prefer the `serve/` layer" in CARD


def test_examples_exist():
    assert SQL_BLOCKS, "expected example queries in the card"
    assert any(RAW_READ.search(b) for b in SQL_BLOCKS), "expected a raw-tree example"


def test_no_raw_tree_example_without_agency_filter():
    for sql in SQL_BLOCKS:
        if RAW_READ.search(sql):
            assert AGENCY_PRED.search(sql), f"raw-tree query without an agency filter:\n{sql}"


def test_no_bare_raw_glob_outside_examples():
    # Any `contracts/**` / `assistance/**` mention in a code block must sit inside a
    # SQL example covered above (i.e. no copy-pasteable unfiltered glob elsewhere).
    code = "\n".join(re.findall(r"```python\n(.*?)```", CARD, flags=re.S))
    stripped = re.sub(r"'''.*?'''", "", code, flags=re.S)
    assert not re.search(r"(contracts|assistance)/\*\*", stripped)
