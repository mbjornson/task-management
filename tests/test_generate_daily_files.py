import pytest
import textwrap
import importlib.util
from pathlib import Path
from unittest.mock import patch
from datetime import datetime

import config

MOCK_CONFIG = {
    "paths": {"tasks_root": "/tmp/tasks"},
    "folders": {"tasks": "tasks", "ideas": "ideas", "bugs": "bugs", "import": "import"},
    "links": {"format": "obsidian"},
    "integrations": {
        "podcast_digest": True,
        "podcast_digest_path": "",
    },
}

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"

with patch.object(config, "get_config", return_value=MOCK_CONFIG):
    with patch.object(config, "CONFIG_FILE", Path("/tmp/fake-config.yaml")):
        spec = importlib.util.spec_from_file_location("generate_daily_files", SCRIPTS_DIR / "generate-daily-files.py")
        gdf = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(gdf)


class TestGetPodcastDigest:
    def test_returns_none_when_no_path_configured(self):
        with patch.object(gdf, "get_podcast_digest_path", return_value=None):
            assert gdf.get_podcast_digest("2026-05-19") is None

    def test_returns_none_when_file_missing(self, tmp_path):
        with patch.object(gdf, "get_podcast_digest_path", return_value=tmp_path):
            assert gdf.get_podcast_digest("2099-01-01") is None

    def test_parses_single_podcast_single_episode(self, tmp_path):
        digest = textwrap.dedent("""\
            ---
            type: digest
            date: 2026-05-19
            ---

            # Daily Digest — 2026-05-19

            ## Test Podcast

            ### Episode One

            **Summary**

            This is the summary paragraph.

            **Key Points**

            - Point one
            - Point two
        """)
        (tmp_path / "2026-05-19.md").write_text(digest)

        with patch.object(gdf, "get_podcast_digest_path", return_value=tmp_path):
            result = gdf.get_podcast_digest("2026-05-19")

        assert len(result) == 1
        assert result[0]["name"] == "Test Podcast"
        assert len(result[0]["episodes"]) == 1
        assert result[0]["episodes"][0]["title"] == "Episode One"
        assert "summary paragraph" in result[0]["episodes"][0]["summary"]

    def test_parses_multiple_podcasts(self, tmp_path):
        digest = textwrap.dedent("""\
            ---
            type: digest
            ---

            # Daily Digest

            ## Podcast A

            ### Episode A1

            **Summary**

            Summary for A1.

            **Key Points**

            - stuff

            ---

            ## Podcast B

            ### Episode B1

            **Summary**

            Summary for B1.

            **Key Points**

            - more stuff
        """)
        (tmp_path / "2026-05-19.md").write_text(digest)

        with patch.object(gdf, "get_podcast_digest_path", return_value=tmp_path):
            result = gdf.get_podcast_digest("2026-05-19")

        assert len(result) == 2
        assert result[0]["name"] == "Podcast A"
        assert result[1]["name"] == "Podcast B"
        assert result[0]["episodes"][0]["summary"] == "Summary for A1."
        assert result[1]["episodes"][0]["summary"] == "Summary for B1."

    def test_horizontal_rules_dont_break_parsing(self, tmp_path):
        digest = textwrap.dedent("""\
            ---
            type: digest
            ---

            # Daily Digest

            ## Podcast One

            ### Ep 1

            **Summary**

            First summary.

            **Key Points**

            - point

            ---

            ## Podcast Two

            ### Ep 2

            **Summary**

            Second summary.

            **Key Points**

            - point

            ---

            ## Podcast Three

            ### Ep 3

            **Summary**

            Third summary.

            **Key Points**

            - point
        """)
        (tmp_path / "2026-05-19.md").write_text(digest)

        with patch.object(gdf, "get_podcast_digest_path", return_value=tmp_path):
            result = gdf.get_podcast_digest("2026-05-19")

        assert len(result) == 3
        names = [p["name"] for p in result]
        assert names == ["Podcast One", "Podcast Two", "Podcast Three"]

    def test_multiple_episodes_per_podcast(self, tmp_path):
        digest = textwrap.dedent("""\
            ---
            type: digest
            ---

            # Daily Digest

            ## My Podcast

            ### First Episode

            **Summary**

            Summary one.

            **Key Points**

            - stuff

            ### Second Episode

            **Summary**

            Summary two.

            **Action Items**

            - do something
        """)
        (tmp_path / "2026-05-19.md").write_text(digest)

        with patch.object(gdf, "get_podcast_digest_path", return_value=tmp_path):
            result = gdf.get_podcast_digest("2026-05-19")

        assert len(result) == 1
        assert len(result[0]["episodes"]) == 2
        assert result[0]["episodes"][0]["title"] == "First Episode"
        assert result[0]["episodes"][1]["title"] == "Second Episode"
        assert result[0]["episodes"][0]["action_items"] == ""
        assert "do something" in result[0]["episodes"][1]["action_items"]

    def test_parses_action_items(self, tmp_path):
        digest = textwrap.dedent("""\
            ---
            type: digest
            ---

            # Daily Digest

            ## Test Pod

            ### Great Episode

            **Summary**

            Summary text here.

            **Key Points**

            - Key point one

            **Action Items**

            - First action item
            - Second action item
            - Read: Some Book by Some Author
        """)
        (tmp_path / "2026-05-19.md").write_text(digest)

        with patch.object(gdf, "get_podcast_digest_path", return_value=tmp_path):
            result = gdf.get_podcast_digest("2026-05-19")

        episode = result[0]["episodes"][0]
        assert episode["summary"] == "Summary text here."
        assert "First action item" in episode["action_items"]
        assert "Second action item" in episode["action_items"]
        assert "Read: Some Book" in episode["action_items"]

    def test_empty_digest_returns_none(self, tmp_path):
        digest = textwrap.dedent("""\
            ---
            type: digest
            ---

            # Daily Digest
        """)
        (tmp_path / "2026-05-19.md").write_text(digest)

        with patch.object(gdf, "get_podcast_digest_path", return_value=tmp_path):
            result = gdf.get_podcast_digest("2026-05-19")

        assert result is None

    def test_multiline_summary(self, tmp_path):
        digest = textwrap.dedent("""\
            ---
            type: digest
            ---

            # Daily Digest

            ## Pod

            ### Ep

            **Summary**

            First paragraph of summary.

            Second paragraph of summary.

            **Key Points**

            - point
        """)
        (tmp_path / "2026-05-19.md").write_text(digest)

        with patch.object(gdf, "get_podcast_digest_path", return_value=tmp_path):
            result = gdf.get_podcast_digest("2026-05-19")

        summary = result[0]["episodes"][0]["summary"]
        assert "First paragraph" in summary
        assert "Second paragraph" in summary


class TestFormatLink:
    def test_obsidian_format(self):
        with patch.object(gdf, "get_link_format", return_value="obsidian"):
            assert gdf.format_link("my-task") == "[[my-task]]"

    def test_obsidian_format_with_folder(self):
        with patch.object(gdf, "get_link_format", return_value="obsidian"):
            assert gdf.format_link("my-task", "tasks") == "[[my-task]]"

    def test_markdown_format(self):
        with patch.object(gdf, "get_link_format", return_value="markdown"):
            assert gdf.format_link("my-task") == "[my-task](my-task.md)"

    def test_markdown_format_with_folder(self):
        with patch.object(gdf, "get_link_format", return_value="markdown"):
            assert gdf.format_link("my-task", "tasks") == "[my-task](tasks/my-task.md)"


class TestFormatDateHeader:
    def test_formats_date(self):
        dt = datetime(2026, 5, 19)
        assert gdf.format_date_header(dt) == "Tuesday, May 19"

    def test_formats_single_digit_day(self):
        dt = datetime(2026, 1, 5)
        assert gdf.format_date_header(dt) == "Monday, January 5"


class TestGenerateDaysBetween:
    def test_single_day(self):
        days = gdf.generate_days_between("2026-05-19", "2026-05-19")
        assert len(days) == 1

    def test_full_week(self):
        days = gdf.generate_days_between("2026-05-18", "2026-05-24")
        assert len(days) == 7

    def test_empty_range(self):
        days = gdf.generate_days_between("2026-05-20", "2026-05-19")
        assert len(days) == 0
