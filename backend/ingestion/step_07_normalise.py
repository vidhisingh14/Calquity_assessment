"""Step 7: type coercion, and the timestamp hazard.

THE HAZARD IN THIS DATASET IS NOT EXCEL SERIAL DATES.

The build spec warns about serial dates ("a value like 45678 is a date, not an
integer") and about answers being "off by years". That failure cannot occur
here: every timestamp in the supplied workbook is already a string of the form
"2026-08-16 09:00". Serial handling is kept below anyway, because a re-export
from Excel could produce them and the cost of keeping it is three lines.

The hazard that IS present is subtler and does not look wrong in a log line:

    the workbook's timestamps are TIMEZONE-NAIVE, while the README snapshot
    carries an explicit zone ("2026-08-16 11:00 Asia/Kolkata").

Treat the naive values as UTC while the snapshot stays IST and everything
shifts by 5.5 hours. That is enough to invert a verdict, not merely to blur
one: ORD-2002's pickup delay is 4h30m against LumenWorks' 4-hour credit
threshold, so a 5.5-hour skew computes -1h and turns an eligible credit into an
ineligible one, with the answer sounding equally confident either way.

So: every naive timestamp is localised to the snapshot's zone, and step 8
asserts no timestamp survived as naive.
"""

from __future__ import annotations

import datetime as dt
import re
from typing import Any
from zoneinfo import ZoneInfo

from app.errors import IngestionError

# Excel's epoch. The 1900 leap-year bug means the practical origin is 1899-12-30.
EXCEL_EPOCH = dt.datetime(1899, 12, 30)

_SNAPSHOT_RE = re.compile(
    r"^\s*(?P<stamp>\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}(?::\d{2})?)\s*(?P<tz>\S+)?\s*$"
)

_TS_FORMATS = ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M")


def parse_snapshot(raw: str) -> dt.datetime:
    """'2026-08-16 11:00 Asia/Kolkata' -> aware datetime.

    The zone named here becomes the zone every naive timestamp in the workbook
    is interpreted in, so it is parsed strictly rather than guessed at.
    """
    match = _SNAPSHOT_RE.match(raw)
    if not match:
        raise IngestionError(f"Cannot parse dataset snapshot value: {raw!r}")

    stamp = match.group("stamp").replace("T", " ")
    tz_name = match.group("tz") or "UTC"
    try:
        tz = ZoneInfo(tz_name)
    except Exception as exc:  # noqa: BLE001
        raise IngestionError(f"Unknown timezone in snapshot value: {tz_name!r}") from exc

    for fmt in _TS_FORMATS:
        try:
            return dt.datetime.strptime(stamp, fmt).replace(tzinfo=tz)
        except ValueError:
            continue
    raise IngestionError(f"Cannot parse snapshot timestamp: {stamp!r}")


def to_datetime(value: Any, tz: ZoneInfo) -> dt.datetime | None:
    """Coerce a cell to an aware datetime in `tz`, or None.

    Handles strings (what this workbook actually contains), real datetimes, and
    Excel serial numbers (defensive). Anything already aware is converted, not
    relabelled, so a genuinely UTC value stays the same instant.
    """
    if value is None or value == "":
        return None

    if isinstance(value, dt.datetime):
        return value.replace(tzinfo=tz) if value.tzinfo is None else value.astimezone(tz)

    if isinstance(value, dt.date):
        return dt.datetime(value.year, value.month, value.day, tzinfo=tz)

    if isinstance(value, (int, float)) and not isinstance(value, bool):
        # Excel serial date. Not present in the supplied pack, kept for re-exports.
        return (EXCEL_EPOCH + dt.timedelta(days=float(value))).replace(tzinfo=tz)

    text = str(value).strip()
    for fmt in _TS_FORMATS:
        try:
            return dt.datetime.strptime(text, fmt).replace(tzinfo=tz)
        except ValueError:
            continue
    try:
        parsed = dt.datetime.fromisoformat(text)
        return parsed.replace(tzinfo=tz) if parsed.tzinfo is None else parsed.astimezone(tz)
    except ValueError as exc:
        raise IngestionError(f"Unparseable timestamp: {value!r}") from exc


def to_bool(value: Any) -> bool | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"true", "yes", "y", "1"}


def to_decimal(value: Any) -> float | None:
    if value is None or value == "":
        return None
    return float(value)


def clean_id(value: Any) -> str | None:
    """IDs get trimmed. A trailing space on an account id is a silent scope
    mismatch that looks like a permissions bug."""
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def normalise_status(value: Any) -> str | None:
    if value is None:
        return None
    return str(value).strip().upper()


def normalise_lower(value: Any) -> str | None:
    if value is None:
        return None
    return str(value).strip().lower()


def assert_within_window(
    stamps: list[tuple[str, dt.datetime]],
    snapshot: dt.datetime,
    years: int = 2,
) -> None:
    """Every timestamp must land in a sane window around the snapshot.

    If dates are wrong, every cancellation and SLA answer is wrong while
    sounding perfectly confident. Better to refuse to ingest.
    """
    low = snapshot - dt.timedelta(days=365 * years)
    high = snapshot + dt.timedelta(days=365 * years)
    bad = [(label, ts) for label, ts in stamps if not (low <= ts <= high)]
    if bad:
        preview = ", ".join(f"{label}={ts.isoformat()}" for label, ts in bad[:5])
        raise IngestionError(
            f"{len(bad)} timestamp(s) outside +/-{years}y of the snapshot "
            f"({snapshot.isoformat()}): {preview}"
        )


def assert_all_aware(stamps: list[tuple[str, dt.datetime]]) -> None:
    """No naive timestamp may survive normalisation.

    This is the assertion that catches the 5.5-hour skew described in this
    module's docstring, which is otherwise invisible until a verdict flips.
    """
    naive = [label for label, ts in stamps if ts.tzinfo is None]
    if naive:
        raise IngestionError(
            f"{len(naive)} timestamp(s) are timezone-naive after normalisation: "
            f"{naive[:5]}. Comparing these against the snapshot would silently "
            f"skew every time-based verdict."
        )
