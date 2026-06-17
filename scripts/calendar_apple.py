#!/usr/bin/env python3
"""
Apple Calendar integration for task-management plugin.

Uses the Apple Calendar MCP server (npx @foxychat-mcp/apple-calendar) when
available so the same server powers both the script and any MCP client. If the
MCP server is not installed or fails, falls back to AppleScript on macOS.
"""

import json
import os
import platform
import re
import signal
import subprocess
import sys
import tempfile
import threading
from datetime import datetime

MCP_TIMEOUT_SECONDS = 8

# MCP server command (same as install-apple-calendar-mcp)
MCP_COMMAND = ["npx", "-y", "@foxychat-mcp/apple-calendar"]


def _call_mcp_get_today_events():
    """
    Call the Apple Calendar MCP server's get_today_events tool via JSON-RPC over stdio.
    Returns list of dicts with start, end, title; or None on any failure.
    """
    result_holder = [None]  # mutable so inner thread can set it
    proc_holder = [None]    # expose proc so outer scope can kill it on timeout

    def run_mcp():
        try:
            proc = subprocess.Popen(
                MCP_COMMAND,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                start_new_session=True,  # new process group so we can kill the whole tree
            )
        except FileNotFoundError:
            return

        proc_holder[0] = proc

        def send(msg):
            proc.stdin.write(json.dumps(msg) + "\n")
            proc.stdin.flush()

        def read_line():
            line = proc.stdout.readline()
            if not line:
                return None
            return line.strip()

        try:
            send({
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "task-management", "version": "1.0.0"},
                },
            })
            init_resp = read_line()
            if not init_resp:
                return
            init = json.loads(init_resp)
            if "error" in init:
                return
            send({"jsonrpc": "2.0", "method": "notifications/initialized"})

            send({
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {"name": "get_today_events", "arguments": {}},
            })
            call_resp = read_line()
            if not call_resp:
                return
            call = json.loads(call_resp)
            if "error" in call:
                return
            result = call.get("result", {})
            content = result.get("content", [])
            if not content:
                result_holder[0] = []
                return
            text = ""
            for item in content:
                if isinstance(item, dict) and item.get("type") == "text":
                    text += item.get("text", "")
            if not text.strip():
                result_holder[0] = []
                return
            result_holder[0] = _parse_mcp_events_text(text)
        except (json.JSONDecodeError, OSError, KeyError):
            pass
        finally:
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            except (OSError, ProcessLookupError):
                try:
                    proc.kill()
                except OSError:
                    pass
            try:
                proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                pass

    t = threading.Thread(target=run_mcp, daemon=True)
    t.start()
    t.join(timeout=MCP_TIMEOUT_SECONDS)
    if t.is_alive():
        # Thread is stuck (npx is hanging). Kill the entire process group so npx
        # and all its children release Calendar.app before we fall back to AppleScript.
        proc = proc_holder[0]
        if proc:
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            except (OSError, ProcessLookupError):
                try:
                    proc.kill()
                except OSError:
                    pass
            try:
                proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                pass
        return None  # timeout → fall back to AppleScript
    return result_holder[0]


def _extract_time(value):
    """Pull a 'H:MM[:SS] AM/PM' time-of-day out of an MCP date/time string.

    The foxychat server emits full datetimes like
    "Wednesday, June 17, 2026 at 11:00:00 AM"; take the part after ' at ' and
    match the clock time. Plain time strings ("9:00 AM") pass through unchanged.
    """
    if not value:
        return ""
    value = str(value)
    if " at " in value:
        value = value.rsplit(" at ", 1)[1]
    m = re.search(r"\d{1,2}:\d{2}(?::\d{2})?\s*[AP]M", value)
    return m.group(0).strip() if m else value.strip()


def _parse_mcp_events_text(text):
    """
    Parse MCP tool output into list of {start, end, title}.
    Handles JSON array or line-based formats (e.g. "10:00 AM - 11:00 AM Title").
    """
    text = text.strip()
    # Try JSON array first
    try:
        data = json.loads(text)
        if isinstance(data, list):
            out = []
            for item in data:
                if isinstance(item, dict):
                    # Server key drift: real foxychat output uses
                    # startDate/endDate/summary, not start/end/title.
                    start = item.get("start", item.get("startTime", item.get("startDate", "")))
                    end = item.get("end", item.get("endTime", item.get("endDate", "")))
                    out.append({
                        "start": _extract_time(start),
                        "end": _extract_time(end),
                        "title": str(item.get("title", item.get("summary", "(No title)"))),
                    })
                elif isinstance(item, str):
                    out.append({"start": "", "end": "", "title": item})
            return out
        if isinstance(data, dict) and "events" in data:
            return _parse_mcp_events_text(json.dumps(data["events"]))
    except json.JSONDecodeError:
        pass

    # Line-based: "start - end title" or "start–end title" or "title (start - end)"
    out = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        # Match "10:00 AM - 11:00 AM Title" or "10:00 AM–11:00 AM Title"
        m = re.match(r"^(.+?)\s*[-–]\s*(.+?)\s+(.+)$", line)
        if m:
            start, end, title = m.group(1).strip(), m.group(2).strip(), m.group(3).strip()
            out.append({"start": start, "end": end, "title": title})
            continue
        # Match "Title (10:00 AM - 11:00 AM)" or "Title (All day)"
        m = re.match(r"^(.+?)\s*\((.+)\)\s*$", line)
        if m:
            title, rest = m.group(1).strip(), m.group(2).strip()
            if rest.lower() == "all day":
                out.append({"start": "12:00:00 AM", "end": "12:00:00 AM", "title": title})
            else:
                parts = re.split(r"\s*[-–]\s*", rest, 1)
                start = parts[0].strip() if parts else ""
                end = parts[1].strip() if len(parts) > 1 else ""
                out.append({"start": start, "end": end, "title": title})
            continue
        out.append({"start": "", "end": "", "title": line})
    return out


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
    """Fetch today's events via AppleScript. calendar_names is a sequence of calendar names."""
    if platform.system() != "Darwin" or not calendar_names:
        return []

    def _esc(s):
        return s.replace("\\", "\\\\").replace('"', '\\"')

    cal_list = "{" + ", ".join(f'"{_esc(n)}"' for n in calendar_names) + "}"

    # Single AppleScript call queries all calendars \u2014 avoids per-calendar subprocess overhead
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
                set startStr to time string of (get start date of e)
                set endStr to time string of (get end date of e)
                set sum to summary of e
                if sum is missing value then set sum to "(No title)"
                set output to output & startStr & tab & endStr & tab & sum & newline
            end repeat
        end try
    end repeat
end tell
return output
"""

    def norm(s):
        return (s or "").strip().replace("\u202f", " ")

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
    """Fetch today's events from ALL calendars in one AppleScript call via bash."""
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
                set startStr to time string of (get start date of e)
                set endStr to time string of (get end date of e)
                set sum to summary of e
                if sum is missing value then set sum to "(No title)"
                set output to output & startStr & tab & endStr & tab & sum & newline
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

    On macOS, AppleScript is authoritative: it queries every calendar and returns
    correct start/end times. The MCP server (npx @foxychat-mcp/apple-calendar) only
    sees a subset of calendars (e.g. just "Siri Suggestions") and can return [] even
    when real meetings exist, so it is a fallback — used when AppleScript finds nothing
    or when not on macOS.

    calendar_names: specific calendars for the AppleScript query. If None/empty, all
                    calendars are queried.
    """
    if platform.system() == "Darwin":
        if calendar_names:
            events = _get_today_events_applescript(calendar_names)
        else:
            # No specific list configured — query all calendars in one AppleScript call,
            # bypassing _get_all_calendar_names() which can fail when Calendar.app is busy.
            events = _get_today_events_all_calendars()
        if events:
            _sort_events(events)
            return events
        # AppleScript found nothing — try MCP before giving up.
        mcp_events = _call_mcp_get_today_events()
        if mcp_events:
            _sort_events(mcp_events)
            return mcp_events
        return []

    # Non-macOS: MCP is the only source.
    mcp_events = _call_mcp_get_today_events()
    if mcp_events is None:
        return []
    _sort_events(mcp_events)
    return mcp_events
