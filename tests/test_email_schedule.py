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


def test_send_via_smtp_orders_starttls_login_send():
    smtp = MagicMock()
    cm = MagicMock()
    cm.__enter__.return_value = smtp
    cm.__exit__.return_value = False
    with patch("smtplib.SMTP", return_value=cm) as mk:
        email_schedule.send_via_smtp("h", 587, "u", "p", "MSG")
    mk.assert_called_once_with("h", 587, timeout=30)
    smtp.starttls.assert_called_once()
    smtp.login.assert_called_once_with("u", "p")
    smtp.send_message.assert_called_once_with("MSG")


def _full_cfg():
    return {
        "recipients": ["to@x.com"],
        "service": "svc",
        "primary": {"from": "o@365.com", "host": "smtp.office365.com", "port": 587},
        "fallback": {"from": "g@gmail.com", "host": "smtp.gmail.com", "port": 587},
    }


def test_primary_success_returns_true():
    with patch.object(email_schedule, "get_keychain_password", return_value="pw"), \
         patch.object(email_schedule, "send_via_smtp") as send:
        ok = email_schedule.send_schedule_email("# x", "2026-06-30", _full_cfg())
    assert ok is True
    assert send.call_count == 1
    assert send.call_args[0][0] == "smtp.office365.com"


def test_primary_fails_falls_back_to_gmail():
    hosts = []

    def fake_send(host, *a, **k):
        hosts.append(host)
        if host == "smtp.office365.com":
            raise email_schedule.smtplib.SMTPAuthenticationError(535, b"blocked")

    with patch.object(email_schedule, "get_keychain_password", return_value="pw"), \
         patch.object(email_schedule, "send_via_smtp", side_effect=fake_send):
        ok = email_schedule.send_schedule_email("# x", "2026-06-30", _full_cfg())
    assert ok is True
    assert hosts == ["smtp.office365.com", "smtp.gmail.com"]


def test_both_fail_returns_false():
    with patch.object(email_schedule, "get_keychain_password", return_value="pw"), \
         patch.object(email_schedule, "send_via_smtp", side_effect=OSError("no network")):
        ok = email_schedule.send_schedule_email("# x", "2026-06-30", _full_cfg())
    assert ok is False


def test_no_recipients_returns_false():
    cfg = _full_cfg()
    cfg["recipients"] = []
    with patch.object(email_schedule, "send_via_smtp") as send:
        ok = email_schedule.send_schedule_email("# x", "2026-06-30", cfg)
    assert ok is False
    send.assert_not_called()


def _send_cfg(tmp_path):
    return {
        "paths": {"tasks_root": str(tmp_path)},
        "integrations": {"email_scheduled": True, "emails": ["a@x.com"], "email_from": "a@x.com"},
    }


def test_maybe_send_disabled(tmp_path):
    cfg = {"paths": {"tasks_root": str(tmp_path)}, "integrations": {"email_scheduled": False}}
    assert email_schedule.maybe_send(cfg, "2026-06-30", tmp_path / "today.md") == "disabled"


def test_maybe_send_skips_when_already_sent(tmp_path):
    (tmp_path / ".schedule-email-sent").write_text("2026-06-30\n")
    (tmp_path / "today.md").write_text("# Today")
    status = email_schedule.maybe_send(_send_cfg(tmp_path), "2026-06-30", tmp_path / "today.md")
    assert "skipped" in status


def test_maybe_send_sends_and_stamps(tmp_path):
    (tmp_path / "today.md").write_text("# Today\n\n- meeting")
    with patch.object(email_schedule, "send_schedule_email", return_value=True) as send:
        status = email_schedule.maybe_send(_send_cfg(tmp_path), "2026-06-30", tmp_path / "today.md")
    assert status == "sent"
    send.assert_called_once()
    assert (tmp_path / ".schedule-email-sent").read_text().strip() == "2026-06-30"


def test_maybe_send_failure_does_not_stamp(tmp_path):
    (tmp_path / "today.md").write_text("# Today")
    with patch.object(email_schedule, "send_schedule_email", return_value=False):
        status = email_schedule.maybe_send(_send_cfg(tmp_path), "2026-06-30", tmp_path / "today.md")
    assert "failed" in status
    assert not (tmp_path / ".schedule-email-sent").exists()
