#!/usr/bin/env python3
"""
Apple Calendar integration for task-management plugin.

On macOS, today's events are read primarily via EventKit (PyObjC) — the same
native API the robust mcp-ical server uses. EventKit sees every calendar and
maps each event independently, so a single malformed event can never truncate
the rest of a calendar's events (the silent-drop bug the old AppleScript loop
had).

If EventKit is unavailable (PyObjC not installed, Calendar permission denied,
or a store-level error), it falls back to a hardened AppleScript reader. The
AppleScript wraps each event's property extraction in its own
``try ... on error ... end try`` so one bad event is skipped instead of
abandoning the remainder of its calendar.

Non-macOS returns [].
"""

import os
import platform
import subprocess
import tempfile
from datetime import datetime, timedelta
from threading import Semaphore

# Guarded so non-macOS (and tests) can import this module without PyObjC, and
# so tests can patch calendar_apple.EKEventStore with a fake store.
try:
    from EventKit import EKEventStore
except Exception:  # pragma: no cover - import guard
    EKEventStore = None


def _fmt_time(dt):
    """Format a datetime as a 12-hour clock string with no leading zero hour.

    Matches the contract the consumer relies on, e.g. "9:30:00 AM",
    "11:00:00 AM", and midnight as "12:00:00 AM" (used to infer all-day events).
    """
    h = dt.hour % 12 or 12
    ampm = "AM" if dt.hour < 12 else "PM"
    return f"{h}:{dt.minute:02d}:{dt.second:02d} {ampm}"


def _eventkit_events_between(start_dt, end_dt, calendar_names=None):
    """Read events in the half-open range [start_dt, end_dt) via EventKit.

    Returns a list of {"start", "end", "title"} dicts (deduped), or None to
    signal the caller to fall back (non-macOS, no PyObjC, access denied, or any
    store-level exception).

    start_dt/end_dt are python datetime objects passed directly to EventKit;
    PyObjC bridges datetime -> NSDate.
    """
    if platform.system() != "Darwin" or EKEventStore is None:
        return None

    try:
        store = EKEventStore.alloc().init()

        # Blocking access request. 0 == EKEntityTypeEvent.
        semaphore = Semaphore(0)
        granted_holder = {"granted": False}

        def completion(granted, error):
            granted_holder["granted"] = bool(granted)
            semaphore.release()

        store.requestAccessToEntityType_completion_(0, completion)
        semaphore.acquire()
        if not granted_holder["granted"]:
            return None

        # Resolve calendars. If specific names are requested, filter to the
        # matching EKCalendar objects; if NONE match, fall back to all calendars
        # (None) so we never silently miss events.
        cals = None
        if calendar_names:
            wanted = set(calendar_names)
            matched = [c for c in store.calendars() if c.title() in wanted]
            cals = matched or None

        predicate = store.predicateForEventsWithStartDate_endDate_calendars_(
            start_dt, end_dt, cals
        )
        ek_events = store.eventsMatchingPredicate_(predicate)
    except Exception:
        return None

    events = []
    for e in ek_events or []:
        try:
            start = datetime.fromtimestamp(e.startDate().timeIntervalSince1970())
            end = datetime.fromtimestamp(e.endDate().timeIntervalSince1970())
            title = e.title() or "(No title)"
            events.append({
                "start": _fmt_time(start),
                "end": _fmt_time(end),
                "title": str(title),
            })
        except Exception:
            # THE FIX: one bad event must NOT drop the rest. Skip and continue.
            continue

    seen = set()
    unique = []
    for e in events:
        key = (e["start"], e["end"], e["title"])
        if key not in seen:
            seen.add(key)
            unique.append(e)
    return unique


def _get_today_events_eventkit(calendar_names=None):
    """Today's events via EventKit, or None to signal fallback.

    Computes today's local bounds and delegates to _eventkit_events_between so
    the date-bounded core can be verified against an arbitrary date.
    """
    start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    end = start + timedelta(days=1)
    return _eventkit_events_between(start, end, calendar_names)


def _get_all_calendar_names():
    """Return list of all calendar names from Calendar.app via AppleScript, or [] on failure."""
    if platform.system() != "Darwin":
        return []
    script = """
tell application "Calendar"
    set out to ""
    repeat with cal in calendars
        set out to out & (name of cal) & "|"
    end repeat
    return out
end tell
"""
    try:
        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return []
    if result.returncode != 0 or not result.stdout:
        return []
    parts = (result.stdout or "").split("|")
    return [p.strip() for p in parts if p.strip()]


def _get_today_events_applescript(calendar_names):
    """Fetch today's events via AppleScript. calendar_names is a sequence of calendar names.

    Defense-in-depth fallback for environments without PyObjC. Each event's
    property extraction is wrapped in its own try/on error so a single bad event
    is skipped instead of abandoning the rest of its calendar.
    """
    if platform.system() != "Darwin" or not calendar_names:
        return []

    def _esc(s):
        return s.replace("\\", "\\\\").replace('"', '\\"')

    cal_list = "{" + ", ".join(f'"{_esc(n)}"' for n in calendar_names) + "}"

    # Single AppleScript call queries all calendars — avoids per-calendar subprocess overhead
    # and the per-calendar timeout that breaks slow Exchange/iCloud calendars.
    script = f"""
set todayStart to (current date)
set hours of todayStart to 0
set minutes of todayStart to 0
set seconds of todayStart to 0
set todayEnd to todayStart + 86400
set calNames to {cal_list}
set tab to character id 9
set newline to character id 10
set output to ""
tell application "Calendar"
    repeat with calName in calNames
        try
            set cal to calendar calName
            set calEvents to (every event of cal whose start date >= todayStart and start date < todayEnd)
            repeat with e in calEvents
                try
                    set startStr to time string of (get start date of e)
                    set endStr to time string of (get end date of e)
                    set sum to summary of e
                    if sum is missing value then set sum to "(No title)"
                    set output to output & startStr & tab & endStr & tab & sum & newline
                on error
                    -- skip just this event and keep reading the rest of the calendar
                end try
            end repeat
        end try
    end repeat
end tell
return output
"""

    def norm(s):
        return (s or "").strip().replace(" ", " ")

    # Write to temp file and run via bash — direct osascript subprocess blocks silently
    # on Exchange/iCloud calendars due to macOS TCC permission scoping.
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".applescript", delete=False) as f:
            f.write(script)
            tmp_path = f.name
        result = subprocess.run(
            ["bash", "-c", f"osascript {tmp_path}"],
            capture_output=True,
            text=True,
            timeout=90,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return []
    finally:
        if tmp_path and os.path.exists(tmp_path):
            os.unlink(tmp_path)
    if result.returncode != 0:
        return []

    events = []
    for line in (result.stdout or "").strip().split("\n"):
        line = line.strip()
        if not line:
            continue
        parts = line.split("\t", 2)
        if len(parts) >= 3:
            events.append({"start": norm(parts[0]), "end": norm(parts[1]), "title": norm(parts[2])})
        elif len(parts) == 2:
            events.append({"start": norm(parts[0]), "end": "", "title": norm(parts[1])})
        else:
            events.append({"start": "", "end": "", "title": norm(parts[0]) if parts else "(No title)"})

    seen = set()
    unique = []
    for e in events:
        key = (e.get("start"), e.get("end"), e.get("title"))
        if key not in seen:
            seen.add(key)
            unique.append(e)
    return unique


def _get_today_events_all_calendars():
    """Fetch today's events from ALL calendars in one AppleScript call via bash.

    Defense-in-depth fallback for environments without PyObjC. Each event's
    property extraction is wrapped in its own try/on error so a single bad event
    is skipped instead of abandoning the rest of its calendar.
    """
    if platform.system() != "Darwin":
        return []

    script = """
set todayStart to (current date)
set hours of todayStart to 0
set minutes of todayStart to 0
set seconds of todayStart to 0
set todayEnd to todayStart + 86400
set tab to character id 9
set newline to character id 10
set output to ""
tell application "Calendar"
    repeat with cal in calendars
        try
            set calEvents to (every event of cal whose start date >= todayStart and start date < todayEnd)
            repeat with e in calEvents
                try
                    set startStr to time string of (get start date of e)
                    set endStr to time string of (get end date of e)
                    set sum to summary of e
                    if sum is missing value then set sum to "(No title)"
                    set output to output & startStr & tab & endStr & tab & sum & newline
                on error
                    -- skip just this event and keep reading the rest of the calendar
                end try
            end repeat
        end try
    end repeat
end tell
return output
"""

    def norm(s):
        return (s or "").strip().replace(" ", " ")

    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".applescript", delete=False) as f:
            f.write(script)
            tmp_path = f.name
        result = subprocess.run(
            ["bash", "-c", f"osascript {tmp_path}"],
            capture_output=True,
            text=True,
            timeout=90,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return []
    finally:
        if tmp_path and os.path.exists(tmp_path):
            os.unlink(tmp_path)
    if result.returncode != 0:
        return []

    events = []
    for line in (result.stdout or "").strip().split("\n"):
        line = line.strip()
        if not line:
            continue
        parts = line.split("\t", 2)
        if len(parts) >= 3:
            events.append({"start": norm(parts[0]), "end": norm(parts[1]), "title": norm(parts[2])})
        elif len(parts) == 2:
            events.append({"start": norm(parts[0]), "end": "", "title": norm(parts[1])})
        else:
            events.append({"start": "", "end": "", "title": norm(parts[0]) if parts else "(No title)"})

    seen = set()
    unique = []
    for e in events:
        key = (e.get("start"), e.get("end"), e.get("title"))
        if key not in seen:
            seen.add(key)
            unique.append(e)
    return unique


def _sort_events(events):
    """Sort events by start time."""
    def sort_key(e):
        s = e.get("start") or ""
        if not s:
            return (0, 0)
        try:
            dt = datetime.strptime(s, "%I:%M:%S %p")
            return (dt.hour * 60 + dt.minute, 0)
        except ValueError:
            try:
                dt = datetime.strptime(s, "%I:%M %p")
                return (dt.hour * 60 + dt.minute, 0)
            except ValueError:
                return (0, 0)
    events.sort(key=sort_key)


def get_today_events(calendar_names=None):
    """
    Return today's events from Apple Calendar as a list of dicts with start, end, title.

    On macOS, EventKit (PyObjC) is authoritative: it sees every calendar and
    maps each event independently, so one malformed event can't truncate the
    rest. If EventKit is unavailable or permission is denied, a hardened
    AppleScript reader is used as a fallback.

    calendar_names: specific calendars to query. If None/empty, all calendars
                    are queried.
    """
    if platform.system() != "Darwin":
        return []

    events = _get_today_events_eventkit(calendar_names)
    if events is None:
        # EventKit unavailable/denied — fall back to hardened AppleScript.
        if calendar_names:
            events = _get_today_events_applescript(calendar_names)
        else:
            events = _get_today_events_all_calendars()

    if events:
        _sort_events(events)
        return events
    return []
