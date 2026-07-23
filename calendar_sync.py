"""Pull the week's meetings from Apple Calendar via icalBuddy.

icalBuddy is invoked with a stable, easy-to-parse layout:

    icalBuddy -nc -npn -b "@EV@" -iep "title,datetime" \
              -df "%Y-%m-%d" -tf "%H:%M" -nrd eventsFrom:<mon> to:<sun+1>

`-nrd` (no relative dates) is essential: without it icalBuddy prints "today",
"tomorrow", etc. for near-term events instead of dates, which the parser drops.

Each event becomes a block:

    @EV@<title>
        <datetime>

where <datetime> is one of:
    2026-12-24                                  (all-day, single)
    2026-07-20 - 2026-07-22                     (all-day, multi-day)
    2026-12-24 at 10:00 - 11:00                 (timed, same day)
    2026-12-24 at 23:00 - 2026-12-25 at 01:00   (timed, crosses midnight)
"""
from __future__ import annotations

import datetime as dt
import re
import shutil
import subprocess

from render import Meeting

BULLET = "@EV@"
_DATE = re.compile(r"(\d{4})-(\d{2})-(\d{2})")
_TIME = re.compile(r"\bat (\d{2}:\d{2})")


class CalendarError(RuntimeError):
    """Raised when icalBuddy is missing or fails."""


def icalbuddy_available() -> bool:
    return shutil.which("icalBuddy") is not None


def list_calendars() -> list[str]:
    """Names of every calendar macOS Calendar knows about (work, holidays, …)."""
    if not icalbuddy_available():
        return []
    try:
        out = subprocess.run(["icalBuddy", "calendars"],
                             capture_output=True, text=True, timeout=15)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return []
    if out.returncode != 0:
        return []
    names = [ln[2:].strip() for ln in out.stdout.splitlines() if ln.startswith("• ")]
    return list(dict.fromkeys(names))           # de-duplicate, keep order


def _run(start: dt.date, end: dt.date, include: list[str] | None = None) -> str:
    cmd = [
        "icalBuddy", "-nc", "-npn", "-b", BULLET,
        "-iep", "title,datetime",
        "-df", "%Y-%m-%d", "-tf", "%H:%M",
        "-nrd",   # force absolute dates (else near-today events print "today"/"tomorrow")
    ]
    if include:
        cmd += ["-ic", ",".join(include)]        # only these calendars
    cmd += [f"eventsFrom:{start:%Y-%m-%d}", f"to:{end:%Y-%m-%d}"]
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    except FileNotFoundError as e:
        raise CalendarError("icalBuddy not found. Install with: brew install ical-buddy") from e
    except subprocess.TimeoutExpired as e:
        raise CalendarError("icalBuddy timed out") from e
    if out.returncode != 0:
        raise CalendarError(out.stderr.strip() or "icalBuddy failed")
    return out.stdout


def _parse_block(block: str):
    """Return (title, start_date, end_date, start_time) or None."""
    lines = [ln for ln in block.splitlines() if ln.strip()]
    if not lines:
        return None
    title = lines[0].strip()
    dt_line = next((ln for ln in lines[1:] if _DATE.search(ln)), "")
    dates = _DATE.findall(dt_line)
    if not dates:
        return None
    start = dt.date(*map(int, dates[0]))
    end = dt.date(*map(int, dates[1])) if len(dates) > 1 else start
    tm = _TIME.search(dt_line)
    start_time = tm.group(1) if tm else ""      # "" => all-day
    return title, start, end, start_time


def fetch_week_meetings(monday: dt.date,
                        include: list[str] | None = None) -> dict[int, list[Meeting]]:
    """Map weekday index (0=Mon … 6=Sun) -> sorted list of Meetings.

    include: only pull from these calendar names. None = all calendars;
    an empty list = no calendars (returns nothing).
    """
    by_day: dict[int, list[Meeting]] = {i: [] for i in range(7)}
    if include is not None and not include:
        return by_day
    for raw in _run(monday, monday + dt.timedelta(days=7), include).split(BULLET):
        if not raw.strip():
            continue
        parsed = _parse_block(raw)
        if not parsed:
            continue
        title, start, end, start_time = parsed
        if start_time:                          # timed -> start day only
            days = [start]
        else:                                   # all-day -> each covered day
            span = (end - start).days
            days = [start + dt.timedelta(days=k) for k in range(max(span, 0) + 1)]
        for d in days:
            idx = (d - monday).days
            if 0 <= idx <= 6:
                by_day[idx].append(Meeting(time=start_time, title=title))

    # all-day first, then by start time
    for items in by_day.values():
        items.sort(key=lambda m: (m.time != "", m.time))
    return by_day


def next_event_date(start: dt.date, horizon_days: int = 180,
                    include: list[str] | None = None) -> dt.date | None:
    """Earliest event date on/after `start` (within horizon). Proves sync works
    even when the chosen week is empty. None if nothing found."""
    if include is not None and not include:
        return None
    try:
        out = _run(start, start + dt.timedelta(days=horizon_days), include)
    except CalendarError:
        return None
    dates = []
    for raw in out.split(BULLET):
        if not raw.strip():
            continue
        parsed = _parse_block(raw)
        if parsed and parsed[1] >= start:
            dates.append(parsed[1])
    return min(dates) if dates else None


if __name__ == "__main__":
    # Self-test against UK Holidays (Christmas week 2026: Mon = Dec 21).
    wk = fetch_week_meetings(dt.date(2026, 12, 21))
    names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    for i in range(7):
        got = ", ".join(f"{m.time or 'all-day'} {m.title}" for m in wk[i]) or "—"
        print(f"{names[i]}: {got}")
