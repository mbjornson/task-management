#!/usr/bin/env python3
"""
Configuration loading utility for task-management plugin.

Loads config from ~/.claude/task-management-config/config.yaml
"""

import yaml
from pathlib import Path

CONFIG_DIR = Path.home() / ".claude" / "task-management-config"
CONFIG_FILE = CONFIG_DIR / "config.yaml"


def get_config():
    """Load and return the configuration dictionary."""
    if not CONFIG_FILE.exists():
        raise FileNotFoundError(
            f"Configuration not found at {CONFIG_FILE}\n"
            "Run /task-management:setup to configure the plugin."
        )
    with open(CONFIG_FILE) as f:
        return yaml.safe_load(f)


def get_tasks_root():
    """Return the tasks root directory as a Path."""
    return Path(get_config()["paths"]["tasks_root"])


def get_folder(name):
    """Return the path to a specific folder within tasks root."""
    config = get_config()
    folder_name = config["folders"].get(name, name)
    return get_tasks_root() / folder_name


def get_all_task_dirs():
    """Return list of directories that may contain task files."""
    return [
        get_folder("tasks"),
        get_folder("ideas"),
        get_folder("bugs"),
        get_folder("import"),
    ]


def get_link_format():
    """Return the link format: 'obsidian' or 'markdown'."""
    config = get_config()
    return config.get("links", {}).get("format", "obsidian")


def is_research_system_enabled():
    """Return True if research-system integration is enabled."""
    config = get_config()
    return config.get("integrations", {}).get("research_system", False)


def is_apple_calendar_enabled():
    """Return True if Apple Calendar integration is enabled."""
    config = get_config()
    return config.get("integrations", {}).get("apple_calendar", False)


def get_apple_calendar_calendars():
    """Return list of calendar names to query, or None to mean 'all calendars' (recommended)."""
    config = get_config()
    names = config.get("integrations", {}).get("apple_calendar_calendars")
    if names is not None and isinstance(names, list) and len(names) > 0:
        return [str(n) for n in names]
    return None  # None = query all calendars (fetched from Calendar.app)


def is_podcast_digest_enabled():
    """Return True if podcast digest integration is enabled."""
    config = get_config()
    return config.get("integrations", {}).get("podcast_digest", False)


def get_podcast_digest_path():
    """Return the path to the podcast digests directory, or None if not set."""
    config = get_config()
    path = config.get("integrations", {}).get("podcast_digest_path")
    if path:
        return Path(path)
    return None


def get_podcast_digest_refresh_cmd():
    """Return the shell command that materializes today's digest, or None.

    Run before reading the digest so /today reflects episodes already ripped
    today (e.g. the ripper's `rip.py --digest`, which rebuilds today's digest
    file from completed episodes) instead of waiting for the full rip to finish.
    """
    config = get_config()
    cmd = config.get("integrations", {}).get("podcast_digest_refresh_cmd")
    return cmd if cmd else None
