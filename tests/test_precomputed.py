"""Data-integrity tests for the precomputed dashboard JSON (site/public/precomputed/).

The landing-page charts read these static files, NOT the live API — so a broken
precompute.py regen ships silently unless something checks the committed output. These
tests load every precomputed file and assert structure + invariants, including the
cross-file contract that the agency index and the per-agency files stay in sync.

All files are committed, so this is fully offline and hermetic.
"""
import json
import math
import os

import pytest

PRECOMPUTED = os.path.join(os.path.dirname(__file__), "..", "site", "public", "precomputed")
DATASETS = ["contracts", "assistance"]


def _load(*parts):
    with open(os.path.join(PRECOMPUTED, *parts)) as f:
        return json.load(f)


def _finite_number(x):
    # JSON's allow_nan lets NaN/Infinity parse; reject them explicitly. bool is an int
    # subclass in Python, so exclude it.
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def _is_count(x):
    return isinstance(x, int) and not isinstance(x, bool) and x >= 0


@pytest.mark.parametrize("ds", DATASETS)
def test_main_file_has_expected_shape(ds):
    d = _load(f"{ds}.json")
    assert set(d) >= {"trend", "kpis", "dims", "years", "timeseries", "lazy_dims", "agencies"}
    years = d["years"]
    assert years == sorted(years) and len(years) == len(set(years))
    assert all(isinstance(y, str) and y.isdigit() and len(y) == 4 for y in years)


@pytest.mark.parametrize("ds", DATASETS)
def test_kpis_and_trend_are_consistent(ds):
    d = _load(f"{ds}.json")
    years = set(d["years"])
    # kpis is keyed by year plus an "all" grand-total. obligations may be negative
    # (deobligations); txn is a non-negative count.
    for y, k in d["kpis"].items():
        assert y in years or y == "all"
        assert _finite_number(k["obl"])
        assert _is_count(k["txn"])
    assert "all" in d["kpis"], "kpis should carry an 'all' grand-total"
    # trend is the kpis per-year series in list form — the years, without the total
    trend_years = {e["fy"] for e in d["trend"]}
    assert trend_years == set(d["kpis"]) - {"all"}
    for e in d["trend"]:
        assert _finite_number(e["obl"]) and _is_count(e["txn"])


@pytest.mark.parametrize("ds", DATASETS)
def test_dims_structure(ds):
    d = _load(f"{ds}.json")
    assert d["dims"], "expected at least one breakdown dimension"
    for key, dim in d["dims"].items():
        assert isinstance(dim["label"], str) and dim["label"]
        assert isinstance(dim["categorical"], bool)
        rows = dim["periods"]["all"]
        assert isinstance(rows, list) and rows
        for r in rows:
            assert isinstance(r["label"], str)
            assert _finite_number(r["obl"]) and _is_count(r["txn"])


@pytest.mark.parametrize("ds", DATASETS)
def test_filters_file_shape(ds):
    f = _load(f"{ds}.filters.json")
    assert f, "filters file should not be empty"
    for field, payload in f.items():
        opts = payload["options"]
        assert isinstance(opts, list)
        for o in opts:
            assert isinstance(o["value"], str) and "label" in o


@pytest.mark.parametrize("ds", DATASETS)
def test_lazy_dim_files_exist(ds):
    d = _load(f"{ds}.json")
    for key in d["lazy_dims"]:
        payload = _load(f"{ds}.{key}.json")          # must exist + parse
        assert payload["periods"]["all"], f"{ds}.{key}.json has no data"


@pytest.mark.parametrize("ds", DATASETS)
def test_county_file_shape(ds):
    c = _load(f"{ds}.county.json")
    assert set(c) >= {"label", "categorical", "periods", "county_names"}
    assert isinstance(c["county_names"], dict) and c["county_names"]
    for r in c["periods"]["all"]:
        assert _finite_number(r["obl"]) and _is_count(r["txn"])


@pytest.mark.parametrize("ds", DATASETS)
def test_agency_index_matches_files_on_disk(ds):
    """The cross-file contract: every agency in the index has a file, and every agency
    file is in the index. A regen that writes one but not the other fails here."""
    d = _load(f"{ds}.json")
    index_slugs = set()
    for a in d["agencies"]:
        assert isinstance(a["name"], str) and isinstance(a["slug"], str)
        index_slugs.add(a["slug"])
    agency_dir = os.path.join(PRECOMPUTED, ds, "agency")
    file_slugs = {fn[:-5] for fn in os.listdir(agency_dir) if fn.endswith(".json")}
    assert index_slugs == file_slugs


@pytest.mark.parametrize("ds", DATASETS)
def test_each_agency_file_parses_and_has_shape(ds):
    d = _load(f"{ds}.json")
    for a in d["agencies"]:
        af = _load(ds, "agency", f"{a['slug']}.json")
        assert set(af) >= {"years", "kpis", "dims", "timeseries", "agency"}
        for y, k in af["kpis"].items():
            assert _finite_number(k["obl"]) and _is_count(k["txn"])
