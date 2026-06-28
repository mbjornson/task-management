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
