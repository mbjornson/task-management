---
description: Install the Apple Calendar MCP server into your MCP client config
---

# install-apple-calendar-mcp

Install the Apple Calendar MCP server into an MCP config file so that (1) `generate-daily-files.py` can call it to fill the **Meetings** section when `integrations.apple_calendar` is enabled, and (2) any MCP client (Cursor, Claude Desktop, etc.) can use the same server. The script does **not** assume Cursor; you choose where to write.

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

### Step 3: macOS permissions (if needed)

On macOS, if calendar tools fail or return no events, grant **Full Disk Access** (or **Automation** for Calendar) to the process that runs the MCP server (e.g. your editor or terminal): **System Settings** → **Privacy & Security** → **Privacy**.

### Step 4: Enable the integration

Set `integrations.apple_calendar: true` in `~/.claude/task-management-config/config.yaml` if not already enabled.

## Summary

The same Apple Calendar MCP server is used by (1) `generate-daily-files.py` (via a small MCP client in the script) and (2) your MCP client. No Cursor-specific paths are assumed; use `MCP_CONFIG_PATH` or `--path` for your client's config.
