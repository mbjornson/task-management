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
