"""Offline tests for the staleness comparison (no network)."""
import datetime as dt

import pytest

from usaspending_archive import staleness

TODAY = dt.date(2026, 10, 23)


def test_manifest_latest():
    m = {"a": {"datestamp": "20260906"}, "b": {"datestamp": "20261006"}, "c": {}}
    assert staleness.manifest_latest(m) == "20261006"
    assert staleness.manifest_latest({}) is None


@pytest.mark.parametrize("today,fy", [(dt.date(2026, 9, 30), 2026), (dt.date(2026, 10, 1), 2027)])
def test_current_fy(today, fy):
    assert staleness.current_fy(today) == fy


def test_fresh_is_ok():
    stale, lines = staleness.assess(archive_full="20261006", manifest_stamp="20261006",
                                    serve_max=dt.date(2026, 10, 4), today=TODAY)
    assert stale is False and lines[0].startswith("OK")


def test_one_missed_cycle_plus_slack_is_stale():
    # archive moved to 11/06, mirror still on 09/06 -> 61 days
    stale, lines = staleness.assess(archive_full="20261106", manifest_stamp="20260906",
                                    serve_max=dt.date(2026, 11, 1), today=TODAY)
    assert stale is True
    assert "manifest is 61 days behind" in lines[0]


def test_serve_stale_while_manifest_current():
    # raw ingested, but serve never rebuilt (the re-chain-forever symptom)
    stale, lines = staleness.assess(archive_full="20261106", manifest_stamp="20261106",
                                    serve_max=dt.date(2026, 9, 30), today=TODAY)
    assert stale is False  # 37 days <= 40: one cycle late alone doesn't trip it
    stale, lines = staleness.assess(archive_full="20261206", manifest_stamp="20261206",
                                    serve_max=dt.date(2026, 9, 30), today=TODAY)
    assert stale is True and "serve layer is 67 days behind" in lines[0]


def test_threshold_boundary():
    # exactly 40 days is not stale; 41 is
    base = dict(manifest_stamp="20261006", today=TODAY)
    assert staleness.assess(archive_full="20261006", serve_max=dt.date(2026, 8, 27), **base)[0] is False
    assert staleness.assess(archive_full="20261006", serve_max=dt.date(2026, 8, 26), **base)[0] is True


def test_missing_inputs_are_stale():
    assert staleness.assess(archive_full="20261006", manifest_stamp=None,
                            serve_max=dt.date(2026, 10, 4), today=TODAY)[0] is True
    assert staleness.assess(archive_full="20261006", manifest_stamp="20261006",
                            serve_max=None, today=TODAY)[0] is True
