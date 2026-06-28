#!/usr/bin/env python3
"""Send the generated today.md as a daily schedule email.

Config-driven (integrations.email_scheduled). Best-effort: callers must ensure a
failure here never breaks file generation. macOS Keychain holds SMTP app
passwords; O365 SMTP is primary with a Gmail fallback.
"""

import smtplib
import subprocess
import sys
from datetime import datetime
from email.message import EmailMessage
from pathlib import Path

STAMP_FILENAME = ".schedule-email-sent"


def get_keychain_password(service, account):
    """Return the generic-password for (service, account) from the macOS Keychain, or None."""
    try:
        result = subprocess.run(
            ["security", "find-generic-password", "-s", service, "-a", account, "-w"],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    pw = (result.stdout or "").rstrip("\n")
    return pw or None
