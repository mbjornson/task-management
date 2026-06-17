"""Tests for the three bugs fixed in calendar_apple.py.

Bug 1 – _get_all_calendar_names used 'character id 0' as a delimiter; macOS
        returns empty output for that, yielding no calendar names and causing
        the event lookup to fall back to ("Calendar", "Work", "Home"), missing
        the user's actual Exchange calendar.  Fixed to use "|".

Bug 2 – _get_today_events_applescript called subprocess.run(['osascript', '-e',
        ...]) once per calendar with a 15-second timeout.  Exchange/iCloud
        calendars take 16+ seconds, so they always timed out.  Fixed to build
        one AppleScript that iterates all calendars and runs it via
        ['bash', '-c', 'osascript <tempfile>'] — routing through bash sidesteps
        the TCC permission block that prevents direct Python-subprocess osascript
        calls from accessing Exchange event data.

Bug 3 – _call_mcp_get_today_events killed only proc.pid on timeout, leaving npx
        child processes alive.  Those children held a Calendar.app connection,
        blocking the AppleScript fallback for the remainder of the run.  Fixed
        to use os.killpg(os.getpgid(proc.pid), SIGKILL) with start_new_session=True
        so the entire process tree is killed at once.
"""

import os
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

import calendar_apple
from calendar_apple import (
    _call_mcp_get_today_events,
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
        stdout = "9:00:00 AM\t9:30:00 AM\tStandup\n"
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


# ─── Bug 3: _call_mcp_get_today_events – kill entire process group on timeout ─


class TestMcpKillsProcessGroupOnTimeout:
    """The old code called proc.kill() on timeout, leaving npx child processes
    alive.  Those children held a Calendar.app connection, blocking the
    AppleScript fallback.  Fixed to os.killpg the whole process group."""

    def _make_hanging_proc(self, block_event):
        """Return a mock Popen proc whose readline blocks until block_event is set."""
        mock_proc = MagicMock()
        mock_proc.pid = 99999
        mock_proc.stdout.readline.side_effect = lambda: (block_event.wait(5), "")[1]
        return mock_proc

    def test_returns_none_on_timeout(self):
        block = threading.Event()
        try:
            with patch("subprocess.Popen", return_value=self._make_hanging_proc(block)), \
                 patch("os.killpg", side_effect=lambda *a: block.set()), \
                 patch("os.getpgid", return_value=99999), \
                 patch.object(calendar_apple, "MCP_TIMEOUT_SECONDS", 0.1):
                result = _call_mcp_get_today_events()
            assert result is None
        finally:
            block.set()

    def test_calls_killpg_not_just_proc_kill_on_timeout(self):
        """Must call os.killpg so the whole npx process tree is torn down."""
        block = threading.Event()
        try:
            with patch("subprocess.Popen", return_value=self._make_hanging_proc(block)), \
                 patch("os.killpg") as mock_killpg, \
                 patch("os.getpgid", return_value=99999), \
                 patch.object(calendar_apple, "MCP_TIMEOUT_SECONDS", 0.1):
                mock_killpg.side_effect = lambda *a: block.set()
                _call_mcp_get_today_events()
            mock_killpg.assert_called_once_with(99999, signal.SIGKILL)
        finally:
            block.set()

    def test_uses_start_new_session_for_process_group(self):
        """start_new_session=True is required so the proc gets its own pgid for killpg."""
        popen_kwargs = {}
        captured = threading.Event()

        def fake_popen(*args, **kwargs):
            popen_kwargs.update(kwargs)
            captured.set()
            raise FileNotFoundError

        with patch("subprocess.Popen", side_effect=fake_popen):
            _call_mcp_get_today_events()

        captured.wait(timeout=2)
        assert popen_kwargs.get("start_new_session") is True

    def test_returns_none_when_npx_not_found(self):
        with patch("subprocess.Popen", side_effect=FileNotFoundError):
            result = _call_mcp_get_today_events()
        assert result is None

    def test_returns_events_on_successful_mcp_response(self):
        import json as _json
        events_json = '[{"start":"9:00 AM","end":"9:30 AM","title":"Standup"}]'
        init_resp = _json.dumps({
            "jsonrpc": "2.0", "id": 1,
            "result": {"protocolVersion": "2024-11-05", "capabilities": {}},
        }) + "\n"
        call_resp = _json.dumps({
            "jsonrpc": "2.0", "id": 2,
            "result": {"content": [{"type": "text", "text": events_json}]},
        }) + "\n"
        responses = iter([init_resp, call_resp, ""])

        mock_proc = MagicMock()
        mock_proc.pid = 12345
        mock_proc.stdout.readline.side_effect = lambda: next(responses, "")

        with patch("subprocess.Popen", return_value=mock_proc):
            result = _call_mcp_get_today_events()

        assert result is not None
        assert len(result) == 1
        assert result[0]["title"] == "Standup"

    def test_returns_empty_list_when_mcp_returns_no_events(self):
        init_resp = '{"jsonrpc":"2.0","id":1,"result":{"protocolVersion":"2024-11-05","capabilities":{}}}\n'
        call_resp = '{"jsonrpc":"2.0","id":2,"result":{"content":[]}}\n'
        responses = iter([init_resp, call_resp, ""])

        mock_proc = MagicMock()
        mock_proc.pid = 12345
        mock_proc.stdout.readline.side_effect = lambda: next(responses, "")

        with patch("subprocess.Popen", return_value=mock_proc):
            result = _call_mcp_get_today_events()

        assert result == []


# ─── AppleScript is the primary source on macOS; MCP is fallback only ────────


class TestAppleScriptIsPrimaryOnDarwin:
    """The MCP server only sees a subset of calendars (e.g. just 'Siri
    Suggestions') and can return [] even when real meetings exist. AppleScript
    queries all calendars and returns times correctly, so on macOS it must run
    first; MCP is only a fallback (non-macOS, or when AppleScript finds nothing)."""

    def test_applescript_runs_first_and_mcp_not_called_when_events_found(self):
        events = [{"start": "11:00:00 AM", "end": "12:00:00 PM", "title": "Catalyst Check-in"}]
        with patch("platform.system", return_value="Darwin"), \
             patch.object(calendar_apple, "_get_today_events_all_calendars", return_value=events) as mock_as, \
             patch.object(calendar_apple, "_call_mcp_get_today_events") as mock_mcp:
            result = calendar_apple.get_today_events(None)
        assert result == events
        mock_as.assert_called_once()
        mock_mcp.assert_not_called()

    def test_falls_back_to_mcp_when_applescript_returns_empty(self):
        mcp_events = [{"start": "9:00:00 AM", "end": "9:30:00 AM", "title": "Standup"}]
        with patch("platform.system", return_value="Darwin"), \
             patch.object(calendar_apple, "_get_today_events_all_calendars", return_value=[]), \
             patch.object(calendar_apple, "_call_mcp_get_today_events", return_value=mcp_events) as mock_mcp:
            result = calendar_apple.get_today_events(None)
        assert result == mcp_events
        mock_mcp.assert_called_once()

    def test_uses_configured_calendars_for_applescript_first(self):
        events = [{"start": "2:00:00 PM", "end": "3:00:00 PM", "title": "Client call"}]
        with patch("platform.system", return_value="Darwin"), \
             patch.object(calendar_apple, "_get_today_events_applescript", return_value=events) as mock_as, \
             patch.object(calendar_apple, "_call_mcp_get_today_events") as mock_mcp:
            result = calendar_apple.get_today_events(["Work"])
        assert result == events
        mock_as.assert_called_once_with(["Work"])
        mock_mcp.assert_not_called()

    def test_non_darwin_uses_mcp(self):
        mcp_events = [{"start": "9:00:00 AM", "end": "9:30:00 AM", "title": "Standup"}]
        with patch("platform.system", return_value="Linux"), \
             patch.object(calendar_apple, "_call_mcp_get_today_events", return_value=mcp_events) as mock_mcp:
            result = calendar_apple.get_today_events(None)
        assert result == mcp_events
        mock_mcp.assert_called_once()


class TestMcpParsesRealServerKeys:
    """The foxychat apple-calendar server emits keys startDate/endDate/summary
    with full datetime strings, e.g. 'Wednesday, June 17, 2026 at 11:00:00 AM'.
    The parser must extract the time-of-day so meetings show with times."""

    def test_parses_startdate_enddate_summary(self):
        text = (
            '[{"summary":"Catalyst Check-in",'
            '"startDate":"Wednesday, June 17, 2026 at 11:00:00 AM",'
            '"endDate":"Wednesday, June 17, 2026 at 12:00:00 PM",'
            '"allDay":false}]'
        )
        events = calendar_apple._parse_mcp_events_text(text)
        assert len(events) == 1
        assert events[0]["title"] == "Catalyst Check-in"
        assert events[0]["start"] == "11:00:00 AM"
        assert events[0]["end"] == "12:00:00 PM"
