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


class TestRefreshPodcastDigest:
    """On-demand refresh: before reading the digest, run the configured command
    (e.g. the ripper's `rip.py --digest`) so today's digest is materialized from
    already-completed episodes instead of waiting for the full rip to finish."""

    def test_runs_configured_command(self):
        with patch.object(gdf, "get_podcast_digest_refresh_cmd", return_value="rip.py --digest"), \
             patch("subprocess.run") as mock_run:
            gdf.refresh_podcast_digest()
        assert mock_run.call_count == 1
        assert mock_run.call_args[0][0] == "rip.py --digest"

    def test_no_op_when_unconfigured(self):
        with patch.object(gdf, "get_podcast_digest_refresh_cmd", return_value=None), \
             patch("subprocess.run") as mock_run:
            gdf.refresh_podcast_digest()
        mock_run.assert_not_called()

    def test_swallows_subprocess_errors(self):
        with patch.object(gdf, "get_podcast_digest_refresh_cmd", return_value="boom"), \
             patch("subprocess.run", side_effect=OSError("nope")):
            # Must not raise — a failed refresh just leaves the placeholder.
            gdf.refresh_podcast_digest()


class TestGenerateTodayDigestSection:
    """today.md always shows a Podcast Digest heading when the integration is on:
    today's episodes if ready, else a 'not ready yet' placeholder (never a
    stale fallback)."""

    @staticmethod
    def _digest(date_str):
        return textwrap.dedent(f"""\
            ---
            type: digest
            date: {date_str}
            ---

            # Daily Digest — {date_str}

            ## My Podcast

            ### Great Episode

            **Summary**

            The summary text.
        """)

    def _patches(self, tmp_path, digests):
        (tmp_path / "tasks").mkdir(exist_ok=True)
        (tmp_path / "ideas").mkdir(exist_ok=True)
        return [
            patch.object(gdf, "BASE_DIR", tmp_path),
            patch.object(gdf, "TASKS_DIR", tmp_path / "tasks"),
            patch.object(gdf, "IDEAS_DIR", tmp_path / "ideas"),
            patch.object(gdf, "is_apple_calendar_enabled", return_value=False),
            patch.object(gdf, "is_podcast_digest_enabled", return_value=True),
            patch.object(gdf, "refresh_podcast_digest"),
            patch.object(gdf, "get_podcast_digest_path", return_value=digests),
        ]

    def test_placeholder_when_today_missing(self, tmp_path):
        digests = tmp_path / "digests"; digests.mkdir()
        (digests / "2026-05-12.md").write_text(self._digest("2026-05-12"))  # older, must be ignored
        import contextlib
        with contextlib.ExitStack() as stack:
            for p in self._patches(tmp_path, digests):
                stack.enter_context(p)
            gdf.generate_today_md({"today": "2026-05-19"})
        content = (tmp_path / "today.md").read_text()
        assert "## Podcast Digest" in content
        assert "not ready yet" in content
        assert "My Podcast" not in content  # no stale fallback

    def test_renders_today_episodes_when_present(self, tmp_path):
        digests = tmp_path / "digests"; digests.mkdir()
        (digests / "2026-05-19.md").write_text(self._digest("2026-05-19"))
        import contextlib
        with contextlib.ExitStack() as stack:
            for p in self._patches(tmp_path, digests):
                stack.enter_context(p)
            gdf.generate_today_md({"today": "2026-05-19"})
        content = (tmp_path / "today.md").read_text()
        assert "## Podcast Digest" in content
        assert "not ready yet" not in content
        assert "### My Podcast" in content
        assert "Great Episode" in content

    def test_calls_refresh_before_reading(self, tmp_path):
        digests = tmp_path / "digests"; digests.mkdir()
        import contextlib
        with contextlib.ExitStack() as stack:
            for p in self._patches(tmp_path, digests):
                stack.enter_context(p)
            # refresh_podcast_digest is patched (a MagicMock) inside _patches
            gdf.generate_today_md({"today": "2026-05-19"})
            assert gdf.refresh_podcast_digest.called


class TestSyncCompletionsFromToday:
    def test_stamps_checked_obsidian_task(self, tmp_path):
        tasks_dir = tmp_path / "tasks"
        tasks_dir.mkdir()
        task_file = tasks_dir / "my-task.md"
        task_file.write_text("---\ntype: task\ndue: 2026-01-01\n---\n# my task\n")

        today_file = tmp_path / "today.md"
        today_file.write_text("## Overdue\n- [x] [[my-task]] (due: 2026-01-01)\n")

        with patch.object(gdf, "BASE_DIR", tmp_path), \
             patch.object(gdf, "TASKS_DIR", tasks_dir), \
             patch.object(gdf, "get_link_format", return_value="obsidian"):
            gdf.sync_completions_from_today("2026-05-20")

        content = task_file.read_text()
        assert "completed: 2026-05-20" in content

    def test_stamps_checked_markdown_task(self, tmp_path):
        tasks_dir = tmp_path / "tasks"
        tasks_dir.mkdir()
        task_file = tasks_dir / "my-task.md"
        task_file.write_text("---\ntype: task\ndue: 2026-01-01\n---\n# my task\n")

        today_file = tmp_path / "today.md"
        today_file.write_text("## Due Today\n- [x] [my-task](tasks/my-task.md)\n")

        with patch.object(gdf, "BASE_DIR", tmp_path), \
             patch.object(gdf, "TASKS_DIR", tasks_dir), \
             patch.object(gdf, "get_link_format", return_value="markdown"):
            gdf.sync_completions_from_today("2026-05-20")

        content = task_file.read_text()
        assert "completed: 2026-05-20" in content

    def test_ignores_unchecked_tasks(self, tmp_path):
        tasks_dir = tmp_path / "tasks"
        tasks_dir.mkdir()
        task_file = tasks_dir / "my-task.md"
        original = "---\ntype: task\ndue: 2026-01-01\n---\n# my task\n"
        task_file.write_text(original)

        today_file = tmp_path / "today.md"
        today_file.write_text("## Overdue\n- [ ] [[my-task]] (due: 2026-01-01)\n")

        with patch.object(gdf, "BASE_DIR", tmp_path), \
             patch.object(gdf, "TASKS_DIR", tasks_dir), \
             patch.object(gdf, "get_link_format", return_value="obsidian"):
            gdf.sync_completions_from_today("2026-05-20")

        assert task_file.read_text() == original

    def test_skips_already_completed_task(self, tmp_path):
        tasks_dir = tmp_path / "tasks"
        tasks_dir.mkdir()
        task_file = tasks_dir / "my-task.md"
        original = "---\ncompleted: 2026-05-19\ntype: task\n---\n# my task\n"
        task_file.write_text(original)

        today_file = tmp_path / "today.md"
        today_file.write_text("## Overdue\n- [x] [[my-task]] (due: 2026-01-01)\n")

        with patch.object(gdf, "BASE_DIR", tmp_path), \
             patch.object(gdf, "TASKS_DIR", tasks_dir), \
             patch.object(gdf, "get_link_format", return_value="obsidian"):
            gdf.sync_completions_from_today("2026-05-20")

        assert task_file.read_text() == original

    def test_no_today_file(self, tmp_path):
        tasks_dir = tmp_path / "tasks"
        tasks_dir.mkdir()

        with patch.object(gdf, "BASE_DIR", tmp_path), \
             patch.object(gdf, "TASKS_DIR", tasks_dir), \
             patch.object(gdf, "get_link_format", return_value="obsidian"):
            gdf.sync_completions_from_today("2026-05-20")


class TestFormatActionItems:
    """Action-item lines from the digest are already markdown tasks ("- [ ] …").
    The formatter must normalize each to a single unchecked checkbox, never
    emitting a double "- [ ] [ ]"."""

    def test_existing_checkbox_not_doubled(self):
        out = gdf._format_action_items("- [ ] Do the thing\n- [ ] Another")
        assert "- [ ] [ ]" not in out
        assert out == "- [ ] Do the thing\n- [ ] Another\n"

    def test_plain_bullet_gets_checkbox(self):
        assert gdf._format_action_items("- Do the thing") == "- [ ] Do the thing\n"

    def test_bare_text_gets_checkbox(self):
        assert gdf._format_action_items("Do the thing") == "- [ ] Do the thing\n"

    def test_checked_box_normalized_to_unchecked(self):
        assert gdf._format_action_items("- [x] Done already") == "- [ ] Done already\n"

    def test_skips_blank_lines(self):
        assert gdf._format_action_items("- [ ] One\n\n- [ ] Two") == "- [ ] One\n- [ ] Two\n"


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


class TestPodcastDigestTodayOnly:
    """Only today's digest counts. A missing/late today-digest must NOT fall
    back to an older one — /today should reflect today's rips, never yesterday's."""

    @staticmethod
    def _digest(date_str, podcast="Pod", episode="Ep", summary="A summary."):
        return textwrap.dedent(f"""\
            ---
            type: digest
            date: {date_str}
            ---

            # Daily Digest — {date_str}

            ## {podcast}

            ### {episode}

            **Summary**

            {summary}
        """)

    def test_does_not_fall_back_when_today_missing(self, tmp_path):
        (tmp_path / "2026-05-10.md").write_text(self._digest("2026-05-10", podcast="Old Pod"))
        (tmp_path / "2026-05-12.md").write_text(self._digest("2026-05-12", podcast="Newer Pod"))
        with patch.object(gdf, "get_podcast_digest_path", return_value=tmp_path):
            result = gdf.get_podcast_digest("2026-05-19")
        assert result is None

    def test_reads_today_when_present(self, tmp_path):
        (tmp_path / "2026-05-12.md").write_text(self._digest("2026-05-12", podcast="Older"))
        (tmp_path / "2026-05-19.md").write_text(self._digest("2026-05-19", podcast="Today"))
        with patch.object(gdf, "get_podcast_digest_path", return_value=tmp_path):
            result = gdf.get_podcast_digest("2026-05-19")
        assert result[0]["name"] == "Today"

    def test_digest_date_is_today_when_present(self, tmp_path):
        (tmp_path / "2026-05-19.md").write_text(self._digest("2026-05-19"))
        with patch.object(gdf, "get_podcast_digest_path", return_value=tmp_path):
            assert gdf.get_podcast_digest_date("2026-05-19") == "2026-05-19"

    def test_digest_date_none_when_today_missing(self, tmp_path):
        (tmp_path / "2026-05-12.md").write_text(self._digest("2026-05-12"))
        with patch.object(gdf, "get_podcast_digest_path", return_value=tmp_path):
            assert gdf.get_podcast_digest_date("2026-05-19") is None

    def test_digest_date_none_when_no_digests(self, tmp_path):
        with patch.object(gdf, "get_podcast_digest_path", return_value=tmp_path):
            assert gdf.get_podcast_digest_date("2026-05-19") is None
