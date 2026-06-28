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


def load_email_config(config):
    """Return resolved email settings, or None if email_scheduled is not enabled."""
    integrations = (config or {}).get("integrations", {}) or {}
    if not integrations.get("email_scheduled", False):
        return None
    recipients = integrations.get("emails") or []
    if isinstance(recipients, str):
        recipients = [recipients]
    return {
        "recipients": [str(r) for r in recipients],
        "service": integrations.get("email_keychain_service", "task-management-smtp"),
        "primary": {
            "from": integrations.get("email_from"),
            "host": integrations.get("email_smtp_host", "smtp.office365.com"),
            "port": int(integrations.get("email_smtp_port", 587)),
        },
        "fallback": {
            "from": integrations.get("email_fallback_from"),
            "host": integrations.get("email_fallback_smtp_host", "smtp.gmail.com"),
            "port": int(integrations.get("email_fallback_smtp_port", 587)),
        },
    }


def _stamp_path(config):
    return Path(config["paths"]["tasks_root"]) / STAMP_FILENAME


def should_send_today(config, today_str):
    """True if the stamp file does not already record today's date."""
    try:
        return _stamp_path(config).read_text().strip() != today_str
    except (FileNotFoundError, OSError):
        return True


def mark_sent_today(config, today_str):
    """Record today's date in the stamp file (best-effort)."""
    try:
        _stamp_path(config).write_text(today_str + "\n")
    except OSError:
        pass


def build_message(markdown_text, subject, sender, recipients):
    """Build a multipart/alternative email: plain-text markdown + rendered HTML."""
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = ", ".join(recipients)
    msg.set_content(markdown_text)  # text/plain
    try:
        import markdown as _md
        html = _md.markdown(markdown_text, extensions=["extra", "sane_lists", "nl2br"])
        msg.add_alternative(f"<html><body>{html}</body></html>", subtype="html")
    except Exception:
        pass  # degrade to text-only if markdown is unavailable
    return msg
