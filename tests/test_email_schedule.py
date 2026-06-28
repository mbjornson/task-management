import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
import email_schedule


def test_keychain_returns_password():
    r = MagicMock(returncode=0, stdout="secret\n")
    with patch("subprocess.run", return_value=r):
        assert email_schedule.get_keychain_password("svc", "acct") == "secret"


def test_keychain_missing_returns_none():
    r = MagicMock(returncode=44, stdout="")
    with patch("subprocess.run", return_value=r):
        assert email_schedule.get_keychain_password("svc", "acct") is None


def test_keychain_security_missing_returns_none():
    with patch("subprocess.run", side_effect=FileNotFoundError):
        assert email_schedule.get_keychain_password("svc", "acct") is None


def test_load_email_config_disabled():
    assert email_schedule.load_email_config({"integrations": {"email_scheduled": False}}) is None


def test_load_email_config_missing_integrations():
    assert email_schedule.load_email_config({}) is None


def test_load_email_config_enabled_defaults():
    cfg = email_schedule.load_email_config({"integrations": {
        "email_scheduled": True,
        "emails": ["a@x.com", "b@y.com"],
        "email_from": "a@x.com",
    }})
    assert cfg["recipients"] == ["a@x.com", "b@y.com"]
    assert cfg["service"] == "task-management-smtp"
    assert cfg["primary"]["host"] == "smtp.office365.com"
    assert cfg["primary"]["port"] == 587
    assert cfg["fallback"]["host"] == "smtp.gmail.com"


def test_load_email_config_string_recipient_coerced_to_list():
    cfg = email_schedule.load_email_config({"integrations": {
        "email_scheduled": True, "emails": "solo@x.com", "email_from": "a@x.com",
    }})
    assert cfg["recipients"] == ["solo@x.com"]


def _paths_cfg(tmp_path):
    return {"paths": {"tasks_root": str(tmp_path)}}


def test_should_send_when_no_stamp(tmp_path):
    assert email_schedule.should_send_today(_paths_cfg(tmp_path), "2026-06-30") is True


def test_should_not_send_when_stamped_today(tmp_path):
    (tmp_path / ".schedule-email-sent").write_text("2026-06-30\n")
    assert email_schedule.should_send_today(_paths_cfg(tmp_path), "2026-06-30") is False


def test_should_send_when_stamp_is_old(tmp_path):
    (tmp_path / ".schedule-email-sent").write_text("2026-06-29\n")
    assert email_schedule.should_send_today(_paths_cfg(tmp_path), "2026-06-30") is True


def test_mark_sent_writes_stamp(tmp_path):
    email_schedule.mark_sent_today(_paths_cfg(tmp_path), "2026-06-30")
    assert (tmp_path / ".schedule-email-sent").read_text().strip() == "2026-06-30"


def test_build_message_headers_and_parts():
    msg = email_schedule.build_message(
        "# Today\n\n- a\n- b", "Schedule for Mon Jun 30", "a@x.com", ["a@x.com", "b@y.com"]
    )
    assert msg["Subject"] == "Schedule for Mon Jun 30"
    assert msg["From"] == "a@x.com"
    assert msg["To"] == "a@x.com, b@y.com"
    content_types = [part.get_content_type() for part in msg.walk()]
    assert "text/plain" in content_types
    assert "text/html" in content_types  # markdown is installed (Step 1)


def test_build_message_plain_text_is_raw_markdown():
    msg = email_schedule.build_message("# Today", "S", "a@x.com", ["a@x.com"])
    plain = [p for p in msg.walk() if p.get_content_type() == "text/plain"][0]
    assert "# Today" in plain.get_content()
