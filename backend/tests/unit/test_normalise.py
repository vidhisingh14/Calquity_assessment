"""The timestamp hazard.

The build spec predicts Excel serial dates and answers "off by years". That
failure cannot occur with the supplied workbook -- every timestamp there is
already a string. The failure that CAN occur is a timezone skew, and it is
worse precisely because it is small: 5.5 hours does not look obviously wrong in
a log line, but it is enough to invert a verdict.

The ORD-2002 case below is the concrete demonstration.
"""

from __future__ import annotations

import datetime as dt
from zoneinfo import ZoneInfo

import pytest

from app.errors import IngestionError
from ingestion import step_07_normalise as norm

IST = ZoneInfo("Asia/Kolkata")
SNAPSHOT = dt.datetime(2026, 8, 16, 11, 0, tzinfo=IST)


def test_parse_snapshot_reads_zone_from_the_readme():
    parsed = norm.parse_snapshot("2026-08-16 11:00 Asia/Kolkata")
    assert parsed == SNAPSHOT
    assert parsed.utcoffset() == dt.timedelta(hours=5, minutes=30)


def test_parse_snapshot_rejects_garbage():
    with pytest.raises(IngestionError):
        norm.parse_snapshot("sometime last Tuesday")


def test_parse_snapshot_rejects_unknown_zone():
    with pytest.raises(IngestionError):
        norm.parse_snapshot("2026-08-16 11:00 Mars/Olympus")


def test_workbook_strings_are_localised_not_left_naive():
    """This is the actual shape in the supplied workbook."""
    value = norm.to_datetime("2026-08-16 09:00", IST)
    assert value.tzinfo is not None
    assert value == dt.datetime(2026, 8, 16, 9, 0, tzinfo=IST)


def test_excel_serial_still_handled():
    """Not present in this pack, but a re-export would produce them."""
    value = norm.to_datetime(46000, IST)
    assert value.tzinfo is not None
    assert value.year == 2025


def test_already_aware_timestamps_keep_their_instant():
    """Converting must not relabel: a genuine UTC value stays the same moment."""
    utc_value = dt.datetime(2026, 8, 16, 5, 30, tzinfo=dt.timezone.utc)
    converted = norm.to_datetime(utc_value, IST)
    assert converted == utc_value
    assert converted.hour == 11  # same instant, expressed in IST


def test_naive_timestamps_are_rejected_by_the_assertion():
    naive = dt.datetime(2026, 8, 16, 9, 0)
    with pytest.raises(IngestionError) as exc:
        norm.assert_all_aware([("ORD-1001.booked_at", naive)])
    assert "naive" in str(exc.value)


def test_out_of_window_timestamps_are_rejected():
    with pytest.raises(IngestionError) as exc:
        norm.assert_within_window(
            [("ORD-1.booked_at", dt.datetime(1970, 1, 1, tzinfo=IST))], SNAPSHOT
        )
    assert "outside" in str(exc.value)


def test_timezone_skew_would_invert_the_ord2002_verdict():
    """Why the assertion above exists, made concrete.

    ORD-2002's pickup window ends 06:30 IST; the snapshot is 11:00 IST. The
    true delay is 4h30m, which clears LumenWorks' 4-hour credit threshold.
    Read the same naive string as UTC and the delay computes as -1h, turning an
    eligible credit into an ineligible one with no error anywhere.
    """
    correct = norm.to_datetime("2026-08-16 06:30", IST)
    delay_hours = (SNAPSHOT - correct).total_seconds() / 3600
    assert delay_hours == pytest.approx(4.5)
    assert delay_hours > 4          # eligible under the LumenWorks contract

    skewed = dt.datetime(2026, 8, 16, 6, 30, tzinfo=dt.timezone.utc)
    skewed_hours = (SNAPSHOT - skewed).total_seconds() / 3600
    assert skewed_hours == pytest.approx(-1.0)
    assert not skewed_hours > 4     # the verdict flips


def test_ids_are_trimmed():
    """A trailing space on an account id is a silent scope mismatch that
    presents as a permissions bug."""
    assert norm.clean_id("  ACCT-001 ") == "ACCT-001"
    assert norm.clean_id("   ") is None


def test_status_casing_normalised():
    assert norm.normalise_status(" booked ") == "BOOKED"
    assert norm.normalise_lower(" OPEN ") == "open"


def test_bools_and_decimals():
    assert norm.to_bool("TRUE") is True
    assert norm.to_bool(False) is False
    assert norm.to_bool(None) is None
    assert norm.to_decimal("4200") == 4200.0
    assert norm.to_decimal(None) is None
