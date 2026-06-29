#!/usr/bin/env python3
"""
Install the Apple Calendar MCP server (mcp-ical) into an MCP client config file.

mcp-ical (https://github.com/Omar-V2/mcp-ical) is a native EventKit (PyObjC)
server. It needs a local clone and `uv`, so this script clones it into
~/.mcp-servers/mcp-ical and runs `uv sync` there before writing the config
(unless the directory already exists).

Does not assume any particular client (e.g. Cursor). You specify where to write
via --path or the MCP_CONFIG_PATH environment variable. If neither is set,
prints the config snippet and common locations so you can add it manually.
"""

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

# mcp-ical is a local server run via uv. Clone target and source repo.
MCP_ICAL_DIR = Path.home() / ".mcp-servers" / "mcp-ical"
MCP_ICAL_REPO = "https://github.com/Omar-V2/mcp-ical.git"

# Server to add: run the local mcp-ical clone via uv.
APPLE_CALENDAR_SERVER = {
    "command": "uv",
    "args": ["--directory", str(MCP_ICAL_DIR), "run", "mcp-ical"],
}

# Common client config paths (for documentation only; we do not write here by default)
COMMON_PATHS = {
    "Cursor": "~/.cursor/mcp.json",
    "Claude Desktop": "~/Library/Application Support/Claude/claude_desktop_config.json",
    "VS Code (MCP extension)": "~/.config/Code/User/globalStorage/mcp.json",
}


def load_mcp_config(path: Path):
    """Load existing config or return empty dict."""
    if not path.exists():
        return {}
    try:
        with open(path) as f:
            data = json.load(f)
            return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError):
        return {}


def save_mcp_config(path: Path, data: dict):
    """Write config, creating parent dir if needed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f, indent=2)
        f.write("\n")


def ensure_mcp_ical_installed() -> bool:
    """Clone mcp-ical and run `uv sync` if the clone doesn't already exist.

    Returns True if the server is ready (already present or freshly installed),
    False if cloning/syncing failed.
    """
    if MCP_ICAL_DIR.exists():
        return True

    print(f"mcp-ical not found at {MCP_ICAL_DIR}; cloning...")
    MCP_ICAL_DIR.parent.mkdir(parents=True, exist_ok=True)
    try:
        subprocess.run(
            ["git", "clone", MCP_ICAL_REPO, str(MCP_ICAL_DIR)],
            check=True,
        )
    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        print(f"Error: failed to clone mcp-ical ({e}).", file=sys.stderr)
        print(f"Clone it manually: git clone {MCP_ICAL_REPO} {MCP_ICAL_DIR}", file=sys.stderr)
        return False

    print(f"Running 'uv sync' in {MCP_ICAL_DIR}...")
    try:
        subprocess.run(
            ["uv", "sync", "--directory", str(MCP_ICAL_DIR)],
            check=True,
        )
    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        print(f"Error: 'uv sync' failed ({e}). Is uv installed?", file=sys.stderr)
        print(f"Run it manually: uv sync --directory {MCP_ICAL_DIR}", file=sys.stderr)
        return False

    return True


def install_into(path: Path) -> bool:
    """
    Add or update the apple-calendar MCP server at path.
    Returns True if config was updated, False if already present and unchanged.
    """
    data = load_mcp_config(path)
    servers = data.get("mcpServers")
    if servers is None:
        data["mcpServers"] = {}
        servers = data["mcpServers"]

    if servers.get("apple-calendar") == APPLE_CALENDAR_SERVER:
        return False

    servers["apple-calendar"] = APPLE_CALENDAR_SERVER
    save_mcp_config(path, data)
    return True


def print_config_only():
    """Print the server config and where to add it for various clients."""
    snippet = {
        "mcpServers": {
            "apple-calendar": APPLE_CALENDAR_SERVER,
        }
    }
    print("Add this to your MCP config (merge into existing mcpServers if present):")
    print()
    print(json.dumps(snippet, indent=2))
    print()
    print("mcp-ical must be cloned locally and synced with uv first:")
    print(f"  git clone {MCP_ICAL_REPO} {MCP_ICAL_DIR}")
    print(f"  uv sync --directory {MCP_ICAL_DIR}")
    print("mcp-ical uses native EventKit (PyObjC), is macOS-only, and needs Calendar permission.")
    print()
    print("Common config file locations:")
    for client, loc in COMMON_PATHS.items():
        expanded = Path(loc).expanduser()
        print(f"  {client}: {expanded}")
    print()
    print("Or set MCP_CONFIG_PATH to your config file and run this script again,")
    print("or pass --path /path/to/your/mcp.json")


def main():
    parser = argparse.ArgumentParser(
        description="Install Apple Calendar MCP server into an MCP config file."
    )
    parser.add_argument(
        "--path",
        type=Path,
        default=None,
        help="Path to MCP config file (e.g. mcp.json). Overrides MCP_CONFIG_PATH.",
    )
    parser.add_argument(
        "--print-only",
        action="store_true",
        help="Only print the config snippet and common paths; do not write any file.",
    )
    args = parser.parse_args()

    if args.print_only:
        print_config_only()
        return

    config_path = args.path
    if config_path is None:
        env_path = os.environ.get("MCP_CONFIG_PATH")
        if env_path:
            config_path = Path(env_path).expanduser()
        else:
            print_config_only()
            print("No --path or MCP_CONFIG_PATH set; no file was written.")
            sys.exit(0)

    # Clone + sync mcp-ical (if needed) before writing the config that points at it.
    if not ensure_mcp_ical_installed():
        print("Warning: mcp-ical is not installed; writing config anyway.", file=sys.stderr)
        print("Finish the install with the git/uv commands above, then reload MCP.", file=sys.stderr)

    config_path = config_path.expanduser().resolve()
    try:
        updated = install_into(config_path)
        if updated:
            print(f"Added Apple Calendar MCP server to {config_path}")
            print("Restart your MCP client or reload MCP for it to take effect.")
            print("mcp-ical is macOS-only and uses native EventKit; grant Calendar access when prompted.")
            print("Launch the MCP client from a terminal/app that has Calendar permission.")
        else:
            print(f"Apple Calendar MCP server is already configured in {config_path}")
    except OSError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
