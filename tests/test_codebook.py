"""Offline tests for codebook parsing — enumerated maps in, prose out."""
from usaspending_archive.codebook import parse_domain_values


def test_parses_enumerated_codes():
    assert parse_domain_values("Y = Yes\nN = No") == [("Y", "Yes"), ("N", "No")]


def test_parses_multichar_and_glob_codes():
    out = parse_domain_values("NP = NEGOTIATED PROPOSAL/QUOTE\nSP1 = SIMPLIFIED ACQUISITION")
    assert out == [("NP", "NEGOTIATED PROPOSAL/QUOTE"), ("SP1", "SIMPLIFIED ACQUISITION")]
    # place-of-performance style codes with glob characters, no spaces
    assert parse_domain_values("00***** = Multi-State") == [("00*****", "Multi-State")]


def test_skips_prose():
    assert parse_domain_values("See https://files.usaspending.gov/reference_data/cfda.csv") == []
    assert parse_domain_values("According to the GSA FPDS, these are listed in the manual") == []
    assert parse_domain_values("") == []


def test_mixed_keeps_only_code_lines():
    # a real-ish blob: two codes plus a trailing prose sentence
    text = "A = MEETS REQUIREMENTS\nB = JUSTIFICATION\nNote that exceptions may apply here"
    assert parse_domain_values(text) == [("A", "MEETS REQUIREMENTS"), ("B", "JUSTIFICATION")]
