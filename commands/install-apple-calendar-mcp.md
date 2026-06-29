---
description: Install the Apple Calendar MCP server into your MCP client config
---

# install-apple-calendar-mcp

Install the [**mcp-ical**](https://github.com/Omar-V2/mcp-ical) Apple Calendar MCP server into an MCP config file so any MCP client (Cursor, Claude Desktop, etc.) can read and manage your calendar. The script does **not** assume Cursor; you choose where to write.

> **Note:** `generate-daily-files.py` no longer uses this MCP server. The plugin's **Meetings** section now reads Apple Calendar directly via native EventKit (PyObjC) in `calendar_apple.py`, with a hardened AppleScript fallback. This MCP install is only for using calendar tools from an MCP client.

mcp-ical is a native **EventKit (PyObjC)** server, so:

- It is **macOS-only** and requires **Calendar permission**.
- It needs a local clone and [`uv`](https://docs.astral.sh/uv/). The installer clones it to `~/.mcp-servers/mcp-ical` and runs `uv sync` there (skipped if the directory already exists).
- The MCP client must be **launched from a terminal/app that has Calendar access** (the permission is inherited from the launching process).

Its tool surface is `list_events(start_date, end_date, calendar_name?)`, `list_calendars`, plus event create/update/delete and search — there is no `get_today_events` / `get_calendar_events`.

## Process

### Step 1: Run the installer

**Option A – Write to a specific config file**

Set the path to your MCP config, then run the script:

```bash
export MCP_CONFIG_PATH=~/.cursor/mcp.json   # or your client's config path
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/install-apple-calendar-mcp.py
```

Or pass the path explicitly:

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/install-apple-calendar-mcp.py --path ~/.cursor/mcp.json
```

**Option B – Print config only (no file written)**

If you prefer to add the server entry yourself:

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/install-apple-calendar-mcp.py --print-only
```

The script prints the JSON to add and common config file locations (Cursor, Claude Desktop, VS Code, etc.). Merge the `apple-calendar` entry into your client's `mcpServers` and save.

### Step 2: Reload MCP in your client

Restart your MCP client or use its “Reload MCP” (or equivalent) so it picks up the new server.

### Step 3: macOS permissions (required)

mcp-ical uses native EventKit, so the **process that launches the MCP client must have Calendar access**. Launch your client from a terminal/app that has been granted Calendar permission under **System Settings** → **Privacy & Security** → **Calendars** (you may be prompted on first use). If calendar tools fail or return no events, this permission is the usual cause.

## Summary

mcp-ical is a native EventKit (PyObjC) Apple Calendar MCP server for your MCP client. It is macOS-only, requires Calendar permission, and is cloned to `~/.mcp-servers/mcp-ical` and run via `uv`. No Cursor-specific paths are assumed; use `MCP_CONFIG_PATH` or `--path` for your client's config. The plugin's own **Meetings** section does **not** depend on this server — it reads Apple Calendar directly via EventKit in `calendar_apple.py`.
