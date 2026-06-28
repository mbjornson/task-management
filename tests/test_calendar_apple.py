"""Tests for calendar_apple.py.

EventKit (PyObjC) is the primary reader on macOS; a hardened AppleScript reader
is the fallback. The historical bugs this guards against:

Bug 1 – _get_all_calendar_names used 'character id 0' as a delimiter; macOS
        returns empty output for that, yielding no calendar names. Fixed to
        use "|".

Bug 2 – _get_today_events_applescript called subprocess.run(['osascript', '-e',
        ...]) once per calendar with a short timeout. Exchange/iCloud calendars
        take 16+ seconds, so they always timed out. Fixed to build one
        AppleScript that iterates all calendars and runs it via
        ['bash', '-c', 'osascript <tempfile>']. The AppleScript now also wraps
        each event's property extraction in its own try/on error so one bad
        event is skipped rather than abandoning the rest of its calendar.

Silent-drop fix – the EventKit reader maps each event inside its own try/except
        so a single event that throws on a property read can never truncate the
        remaining events (the root cause of the dropped "Coffee Bob MacNeal").
"""

import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

import calendar_apple
from calendar_apple import (
    _get_all_calendar_names,
    _get_today_events_all_calendars,
    _get_today_events_applescript,
)


def _run_result(stdout="", returncode=0):
    r = MagicMock()
    r.returncode = returncode
    r.stdout = stdout
    r.stderr = ""
    return r


# ─── Bug 1: _get_all_calendar_names – pipe delimiter ─────────────────────────


class TestGetAllCalendarNamesPipeDelimiter:
    def test_script_uses_pipe_not_null_byte(self):
        """The AppleScript must delimit names with '|', not 'character id 0'.
        The old null-byte delimiter causes macOS to silently return empty output."""
        with patch("subprocess.run", return_value=_run_result("")) as mock_run, \
             patch("platform.system", return_value="Darwin"):
            _get_all_calendar_names()
        script = mock_run.call_args[0][0][2]  # ['osascript', '-e', SCRIPT]
        assert '"|"' in script
        assert "character id 0" not in script

    def test_parses_pipe_delimited_output(self):
        names = "Calendar|Work|Home|matt.bjornson@nerdnoir.com|"
        with patch("subprocess.run", return_value=_run_result(names)), \
             patch("platform.system", return_value="Darwin"):
            result = _get_all_calendar_names()
        assert result == ["Calendar", "Work", "Home", "matt.bjornson@nerdnoir.com"]

    def test_empty_stdout_returns_empty_list(self):
        """Replicates the old null-byte bug: macOS returns '' → function yields []."""
        with patch("subprocess.run", return_value=_run_result("")), \
             patch("platform.system", return_value="Darwin"):
            assert _get_all_calendar_names() == []

    def test_nonzero_returncode_returns_empty_list(self):
        with patch("subprocess.run", return_value=_run_result("Calendar|Work|", returncode=1)), \
             patch("platform.system", return_value="Darwin"):
            assert _get_all_calendar_names() == []

    def test_timeout_returns_empty_list(self):
        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired(["osascript"], 10)), \
             patch("platform.system", return_value="Darwin"):
            assert _get_all_calendar_names() == []

    def test_strips_whitespace_from_names(self):
        with patch("subprocess.run", return_value=_run_result(" Calendar | Work | ")), \
             patch("platform.system", return_value="Darwin"):
            assert _get_all_calendar_names() == ["Calendar", "Work"]

    def test_non_darwin_returns_empty_without_subprocess(self):
        with patch("platform.system", return_value="Linux"), \
             patch("subprocess.run") as mock_run:
            result = _get_all_calendar_names()
        assert result == []
        mock_run.assert_not_called()


# ─── Bug 2: _get_today_events_applescript – single bash-routed subprocess ─────


class TestGetTodayEventsAppleScriptBashRouting:
    def test_uses_bash_not_direct_osascript(self):
        """Must call ['bash', '-c', 'osascript <file>'], not ['osascript', '-e', ...]."""
        with patch("subprocess.run", return_value=_run_result()) as mock_run, \
             patch("platform.system", return_value="Darwin"):
            _get_today_events_applescript(["Calendar"])
        cmd = mock_run.call_args[0][0]
        assert cmd[0] == "bash"
        assert cmd[1] == "-c"
        assert "osascript" in cmd[2]

    def test_does_not_call_osascript_with_e_flag(self):
        """The old code used ['osascript', '-e', script] which is TCC-blocked."""
        with patch("subprocess.run", return_value=_run_result()) as mock_run, \
             patch("platform.system", return_value="Darwin"):
            _get_today_events_applescript(["Work"])
        cmd = mock_run.call_args[0][0]
        assert cmd[0] != "osascript"

    def test_single_subprocess_call_for_multiple_calendars(self):
        """Old code made one subprocess call per calendar; new code makes exactly one."""
        with patch("subprocess.run", return_value=_run_result()) as mock_run, \
             patch("platform.system", return_value="Darwin"):
            _get_today_events_applescript(["Cal A", "Cal B", "Cal C"])
        assert mock_run.call_count == 1

    def test_applescript_has_per_event_error_handling(self):
        """The generated AppleScript must guard each event with its own
        try/on error INSIDE the event loop, so one bad event is skipped rather
        than aborting the rest of the calendar (the silent-drop fix)."""
        captured = {}

        def capture(cmd, *a, **k):
            # Read the temp AppleScript file the function just wrote.
            path = cmd[2].split("osascript ", 1)[1].strip()
            captured["script"] = Path(path).read_text(encoding="utf-8")
            return _run_result()

        with patch("subprocess.run", side_effect=capture), \
             patch("platform.system", return_value="Darwin"):
            _get_today_events_applescript(["Work"])

        script = captured["script"]
        assert "repeat with e in calEvents" in script
        loop_start = script.index("repeat with e in calEvents")
        # The per-event guard (try ... on error) must appear inside the loop.
        assert "on error" in script[loop_start:]
        assert "try" in script[loop_start:]

    def test_parses_tab_separated_events(self):
        stdout = "9:00:00 AM\t9:30:00 AM\tStandup\n11:00:00 AM\t12:00:00 PM\tTeam Meeting\n"
        with patch("subprocess.run", return_value=_run_result(stdout)), \
             patch("platform.system", return_value="Darwin"):
            events = _get_today_events_applescript(["Work"])
        assert len(events) == 2
        assert events[0] == {"start": "9:00:00 AM", "end": "9:30:00 AM", "title": "Standup"}
        assert events[1] == {"start": "11:00:00 AM", "end": "12:00:00 PM", "title": "Team Meeting"}

    def test_deduplicates_events(self):
        """Same event in multiple calendars (e.g. Siri Suggestions mirrors) deduped."""
        stdout = (
            "9:00:00 AM\t9:30:00 AM\tStandup\n"
            "9:00:00 AM\t9:30:00 AM\tStandup\n"
        )
        with patch("subprocess.run", return_value=_run_result(stdout)), \
             patch("platform.system", return_value="Darwin"):
            events = _get_today_events_applescript(["Calendar", "Siri Suggestions"])
        assert len(events) == 1

    def test_normalizes_narrow_no_break_space_in_times(self):
        """AppleScript time strings use U+202F (narrow no-break space); must become plain space."""
        stdout = "9:00:00 AM\t9:30:00 AM\tStandup\n"
        with patch("subprocess.run", return_value=_run_result(stdout)), \
             patch("platform.system", return_value="Darwin"):
            events = _get_today_events_applescript(["Work"])
        assert events[0]["start"] == "9:00:00 AM"
        assert events[0]["end"] == "9:30:00 AM"

    def test_timeout_returns_empty_list(self):
        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired(["bash"], 90)), \
             patch("platform.system", return_value="Darwin"):
            assert _get_today_events_applescript(["Calendar"]) == []

    def test_nonzero_returncode_returns_empty_list(self):
        with patch("subprocess.run", return_value=_run_result("", returncode=1)), \
             patch("platform.system", return_value="Darwin"):
            assert _get_today_events_applescript(["Calendar"]) == []

    def test_empty_calendar_list_returns_empty_without_subprocess(self):
        with patch("subprocess.run") as mock_run, \
             patch("platform.system", return_value="Darwin"):
            result = _get_today_events_applescript([])
        assert result == []
        mock_run.assert_not_called()

    def test_temp_file_deleted_on_success(self, tmp_path):
        created = []
        original_ntf = __import__("tempfile").NamedTemporaryFile

        def tracking_ntf(*args, **kwargs):
            kwargs["dir"] = str(tmp_path)
            f = original_ntf(*args, **kwargs)
            created.append(f.name)
            return f

        with patch("subprocess.run", return_value=_run_result()), \
             patch("platform.system", return_value="Darwin"), \
             patch("tempfile.NamedTemporaryFile", side_effect=tracking_ntf):
            _get_today_events_applescript(["Calendar"])

        assert created, "expected at least one temp file to be created"
        for path in created:
            assert not os.path.exists(path), f"temp file not cleaned up: {path}"

    def test_temp_file_deleted_on_timeout(self, tmp_path):
        created = []
        original_ntf = __import__("tempfile").NamedTemporaryFile

        def tracking_ntf(*args, **kwargs):
            kwargs["dir"] = str(tmp_path)
            f = original_ntf(*args, **kwargs)
            created.append(f.name)
            return f

        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired(["bash"], 90)), \
             patch("platform.system", return_value="Darwin"), \
             patch("tempfile.NamedTemporaryFile", side_effect=tracking_ntf):
            _get_today_events_applescript(["Calendar"])

        assert created, "expected at least one temp file to be created"
        for path in created:
            assert not os.path.exists(path), f"temp file not cleaned up after timeout: {path}"


# ─── EventKit is the primary source on macOS; AppleScript is the fallback ─────


class TestEventKitIsPrimaryOnDarwin:
    """On macOS EventKit runs first. It only falls back to AppleScript when
    EventKit signals unavailability/denial by returning None."""

    def test_eventkit_runs_first_and_applescript_not_called_when_events_found(self):
        events = [{"start": "11:00:00 AM", "end": "12:00:00 PM", "title": "Catalyst Check-in"}]
        with patch("platform.system", return_value="Darwin"), \
             patch.object(calendar_apple, "_get_today_events_eventkit", return_value=events) as mock_ek, \
             patch.object(calendar_apple, "_get_today_events_all_calendars") as mock_all, \
             patch.object(calendar_apple, "_get_today_events_applescript") as mock_named:
            result = calendar_apple.get_today_events(None)
        assert result == events
        mock_ek.assert_called_once()
        mock_all.assert_not_called()
        mock_named.assert_not_called()

    def test_falls_back_to_applescript_when_eventkit_returns_none(self):
        as_events = [{"start": "9:00:00 AM", "end": "9:30:00 AM", "title": "Standup"}]
        with patch("platform.system", return_value="Darwin"), \
             patch.object(calendar_apple, "_get_today_events_eventkit", return_value=None), \
             patch.object(calendar_apple, "_get_today_events_all_calendars", return_value=as_events) as mock_all:
            result = calendar_apple.get_today_events(None)
        assert result == as_events
        mock_all.assert_called_once()

    def test_falls_back_to_named_applescript_when_eventkit_returns_none(self):
        as_events = [{"start": "2:00:00 PM", "end": "3:00:00 PM", "title": "Client call"}]
        with patch("platform.system", return_value="Darwin"), \
             patch.object(calendar_apple, "_get_today_events_eventkit", return_value=None), \
             patch.object(calendar_apple, "_get_today_events_applescript", return_value=as_events) as mock_named:
            result = calendar_apple.get_today_events(["Work"])
        assert result == as_events
        mock_named.assert_called_once_with(["Work"])

    def test_non_darwin_returns_empty(self):
        with patch("platform.system", return_value="Linux"), \
             patch.object(calendar_apple, "_get_today_events_eventkit") as mock_ek:
            result = calendar_apple.get_today_events(None)
        assert result == []
        mock_ek.assert_not_called()


# ─── EventKit reader unit tests (the silent-drop fix) ────────────────────────


def _fake_event(title, start_dt, end_dt):
    """Build a fake EKEvent mock with title()/startDate()/endDate()."""
    e = MagicMock()
    e.title.return_value = title
    e.startDate.return_value.timeIntervalSince1970.return_value = start_dt.timestamp()
    e.endDate.return_value.timeIntervalSince1970.return_value = end_dt.timestamp()
    return e


def _fake_store(events, granted=True):
    """Build a fake EKEventStore instance whose access completion is synchronous."""
    store = MagicMock()

    def request_access(entity_type, completion):
        completion(granted, None)

    store.requestAccessToEntityType_completion_.side_effect = request_access
    store.calendars.return_value = []
    store.predicateForEventsWithStartDate_endDate_calendars_.return_value = "PREDICATE"
    store.eventsMatchingPredicate_.return_value = events
    return store


def _patch_ekstore(store):
    """Patch calendar_apple.EKEventStore so .alloc().init() returns store."""
    fake_cls = MagicMock()
    fake_cls.alloc.return_value.init.return_value = store
    return patch.object(calendar_apple, "EKEventStore", fake_cls)


class TestEventKitReader:
    def test_maps_events_to_dict_contract_with_formatted_times(self):
        events = [
            _fake_event("Standup", datetime(2026, 6, 29, 9, 0, 0), datetime(2026, 6, 29, 9, 30, 0)),
            _fake_event("Lunch", datetime(2026, 6, 29, 12, 0, 0), datetime(2026, 6, 29, 13, 0, 0)),
        ]
        store = _fake_store(events)
        with patch("platform.system", return_value="Darwin"), _patch_ekstore(store):
            result = calendar_apple._eventkit_events_between(
                datetime(2026, 6, 29), datetime(2026, 6, 30)
            )
        assert result == [
            {"start": "9:00:00 AM", "end": "9:30:00 AM", "title": "Standup"},
            {"start": "12:00:00 PM", "end": "1:00:00 PM", "title": "Lunch"},
        ]

    def test_bad_event_is_skipped_others_returned(self):
        """A single event that raises on property access must NOT drop the rest
        (the anti-truncation fix)."""
        good1 = _fake_event("Before", datetime(2026, 6, 29, 8, 0, 0), datetime(2026, 6, 29, 8, 30, 0))
        bad = MagicMock()
        bad.startDate.side_effect = RuntimeError("boom on property read")
        good2 = _fake_event("After", datetime(2026, 6, 29, 10, 0, 0), datetime(2026, 6, 29, 10, 30, 0))
        store = _fake_store([good1, bad, good2])
        with patch("platform.system", return_value="Darwin"), _patch_ekstore(store):
            result = calendar_apple._eventkit_events_between(
                datetime(2026, 6, 29), datetime(2026, 6, 30)
            )
        titles = [e["title"] for e in result]
        assert titles == ["Before", "After"]

    def test_dedups_identical_events(self):
        e1 = _fake_event("Standup", datetime(2026, 6, 29, 9, 0, 0), datetime(2026, 6, 29, 9, 30, 0))
        e2 = _fake_event("Standup", datetime(2026, 6, 29, 9, 0, 0), datetime(2026, 6, 29, 9, 30, 0))
        store = _fake_store([e1, e2])
        with patch("platform.system", return_value="Darwin"), _patch_ekstore(store):
            result = calendar_apple._eventkit_events_between(
                datetime(2026, 6, 29), datetime(2026, 6, 30)
            )
        assert len(result) == 1

    def test_no_title_falls_back_to_placeholder(self):
        e = _fake_event(None, datetime(2026, 6, 29, 9, 0, 0), datetime(2026, 6, 29, 9, 30, 0))
        store = _fake_store([e])
        with patch("platform.system", return_value="Darwin"), _patch_ekstore(store):
            result = calendar_apple._eventkit_events_between(
                datetime(2026, 6, 29), datetime(2026, 6, 30)
            )
        assert result[0]["title"] == "(No title)"

    def test_access_denied_returns_none(self):
        store = _fake_store([], granted=False)
        with patch("platform.system", return_value="Darwin"), _patch_ekstore(store):
            result = calendar_apple._eventkit_events_between(
                datetime(2026, 6, 29), datetime(2026, 6, 30)
            )
        assert result is None

    def test_eventkit_unavailable_returns_none(self):
        with patch("platform.system", return_value="Darwin"), \
             patch.object(calendar_apple, "EKEventStore", None):
            result = calendar_apple._eventkit_events_between(
                datetime(2026, 6, 29), datetime(2026, 6, 30)
            )
        assert result is None

    def test_non_darwin_returns_none(self):
        store = _fake_store([])
        with patch("platform.system", return_value="Linux"), _patch_ekstore(store):
            result = calendar_apple._eventkit_events_between(
                datetime(2026, 6, 29), datetime(2026, 6, 30)
            )
        assert result is None

    def test_calendar_filter_falls_back_to_all_when_no_name_matches(self):
        """If a requested calendar name matches none, we pass None (all calendars)
        to the predicate so we never silently miss everything."""
        cal = MagicMock()
        cal.title.return_value = "Work"
        e = _fake_event("Meeting", datetime(2026, 6, 29, 9, 0, 0), datetime(2026, 6, 29, 9, 30, 0))
        store = _fake_store([e])
        store.calendars.return_value = [cal]
        with patch("platform.system", return_value="Darwin"), _patch_ekstore(store):
            calendar_apple._eventkit_events_between(
                datetime(2026, 6, 29), datetime(2026, 6, 30),
                calendar_names=["Nonexistent"],
            )
        # cals arg (3rd positional) must be None when nothing matched.
        _, _, cals = store.predicateForEventsWithStartDate_endDate_calendars_.call_args[0]
        assert cals is None

    def test_calendar_filter_passes_matching_calendars(self):
        work = MagicMock()
        work.title.return_value = "Work"
        home = MagicMock()
        home.title.return_value = "Home"
        e = _fake_event("Meeting", datetime(2026, 6, 29, 9, 0, 0), datetime(2026, 6, 29, 9, 30, 0))
        store = _fake_store([e])
        store.calendars.return_value = [work, home]
        with patch("platform.system", return_value="Darwin"), _patch_ekstore(store):
            calendar_apple._eventkit_events_between(
                datetime(2026, 6, 29), datetime(2026, 6, 30),
                calendar_names=["Work"],
            )
        _, _, cals = store.predicateForEventsWithStartDate_endDate_calendars_.call_args[0]
        assert cals == [work]

    def test_today_eventkit_delegates_to_between(self):
        sentinel = [{"start": "9:00:00 AM", "end": "9:30:00 AM", "title": "Standup"}]
        with patch.object(calendar_apple, "_eventkit_events_between", return_value=sentinel) as mock_between:
            result = calendar_apple._get_today_events_eventkit(["Work"])
        assert result == sentinel
        # Called with a midnight start, +1 day end, and the calendar names.
        args, _ = mock_between.call_args
        start, end, names = args
        assert (start.hour, start.minute, start.second, start.microsecond) == (0, 0, 0, 0)
        assert (end - start).days == 1
        assert names == ["Work"]
