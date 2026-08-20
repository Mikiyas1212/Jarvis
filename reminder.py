"""
reminder.py — schedule a spoken reminder for a parsed time/date.

Speaks the reminder aloud and logs it when the time arrives. Time/date parsing
is unchanged from the original; the plumbing now goes through assistant_io so
we don't spin up a fresh event loop per reminder or duplicate the speak code.
"""

import re
import time
import threading
from datetime import datetime, timedelta

import pytz

from assistant_io import say, State, set_state

TIMEZONE = pytz.timezone("Africa/Addis_Ababa")

_WEEKDAYS = {"monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
             "friday": 4, "saturday": 5, "sunday": 6}


def _parse_reminder_time(time_str: str, date_str: str) -> float:
    """
    Convert time_str ('3pm', '15:30', '9:00 am') plus an optional date_str
    ('tomorrow', 'monday') into a Unix timestamp. Returns 0.0 on failure.
    """
    now = datetime.now(TIMEZONE)
    ts = (time_str or "").strip().lower()

    hour, minute = None, 0
    m12 = re.match(r'(\d{1,2})(?::(\d{2}))?\s*(am|pm)', ts)
    m24 = re.match(r'(\d{1,2}):(\d{2})', ts)

    if m12:
        hour = int(m12.group(1))
        minute = int(m12.group(2)) if m12.group(2) else 0
        if m12.group(3) == 'pm' and hour != 12:
            hour += 12
        elif m12.group(3) == 'am' and hour == 12:
            hour = 0
    elif m24:
        hour, minute = int(m24.group(1)), int(m24.group(2))

    if hour is None:
        return 0.0

    target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    ds = (date_str or "").strip().lower()

    if ds == "tomorrow":
        target += timedelta(days=1)
    elif ds in _WEEKDAYS:
        delta = (_WEEKDAYS[ds] - now.weekday()) % 7
        if delta == 0 and target <= now:
            delta = 7
        target += timedelta(days=delta)
    elif target <= now:                 # "today"/unspecified and already passed
        target += timedelta(days=1)

    return target.timestamp()


def _reminder_thread(params: dict, player=None) -> None:
    message = params.get('message', 'Reminder')
    target_ts = _parse_reminder_time(params.get('time', ''), params.get('date', ''))

    if target_ts <= 0:
        print(f"[reminder] could not parse time '{params.get('time')}', firing in 60s")
        target_ts = time.time() + 60

    wait_secs = max(0.0, target_ts - time.time())
    print(f"[reminder] waiting {wait_secs:.0f}s for: {message!r}")
    time.sleep(wait_secs)

    say(player, f"Sir, this is your reminder: {message}.")


def reminder(params: dict, player=None) -> None:
    """Entry point called by smart_execute — fires the reminder off-thread."""
    threading.Thread(target=_reminder_thread, args=(params, player),
                     daemon=True).start()
