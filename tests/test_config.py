import pytest
from pathlib import Path
from unittest.mock import patch

import config


SAMPLE_CONFIG = {
    "paths": {"tasks_root": "/tmp/tasks"},
    "folders": {"tasks": "tasks", "ideas": "ideas", "bugs": "bugs", "import": "import"},
    "links": {"format": "obsidian"},
    "integrations": {
        "research_system": True,
        "apple_calendar": False,
        "podcast_digest": True,
        "podcast_digest_path": "/tmp/digests",
    },
}


@pytest.fixture
def mock_config():
    with patch.object(config, "get_config", return_value=SAMPLE_CONFIG):
        yield


def test_get_tasks_root(mock_config):
    assert config.get_tasks_root() == Path("/tmp/tasks")


def test_get_folder(mock_config):
    assert config.get_folder("tasks") == Path("/tmp/tasks/tasks")
    assert config.get_folder("ideas") == Path("/tmp/tasks/ideas")


def test_get_folder_fallback(mock_config):
    assert config.get_folder("unknown") == Path("/tmp/tasks/unknown")


def test_get_link_format_obsidian(mock_config):
    assert config.get_link_format() == "obsidian"


def test_get_link_format_default():
    with patch.object(config, "get_config", return_value={"paths": {"tasks_root": "/tmp"}}):
        assert config.get_link_format() == "obsidian"


def test_is_research_system_enabled(mock_config):
    assert config.is_research_system_enabled() is True


def test_is_apple_calendar_enabled(mock_config):
    assert config.is_apple_calendar_enabled() is False


def test_is_podcast_digest_enabled(mock_config):
    assert config.is_podcast_digest_enabled() is True


def test_get_podcast_digest_path(mock_config):
    assert config.get_podcast_digest_path() == Path("/tmp/digests")


def test_get_podcast_digest_path_empty():
    cfg = {**SAMPLE_CONFIG, "integrations": {}}
    with patch.object(config, "get_config", return_value=cfg):
        assert config.get_podcast_digest_path() is None


def test_get_apple_calendar_calendars_none(mock_config):
    assert config.get_apple_calendar_calendars() is None


def test_get_apple_calendar_calendars_list():
    cfg = {**SAMPLE_CONFIG, "integrations": {**SAMPLE_CONFIG["integrations"], "apple_calendar_calendars": ["Work", "Personal"]}}
    with patch.object(config, "get_config", return_value=cfg):
        assert config.get_apple_calendar_calendars() == ["Work", "Personal"]


def test_get_podcast_digest_refresh_cmd_set():
    cfg = {**SAMPLE_CONFIG, "integrations": {
        **SAMPLE_CONFIG["integrations"],
        "podcast_digest_refresh_cmd": "python3 /x/rip.py --digest",
    }}
    with patch.object(config, "get_config", return_value=cfg):
        assert config.get_podcast_digest_refresh_cmd() == "python3 /x/rip.py --digest"


def test_get_podcast_digest_refresh_cmd_none(mock_config):
    assert config.get_podcast_digest_refresh_cmd() is None


def test_config_file_not_found():
    with patch.object(config, "CONFIG_FILE", Path("/nonexistent/config.yaml")):
        with pytest.raises(FileNotFoundError):
            config.get_config()
