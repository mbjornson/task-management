# Email Daily Schedule — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** After the daily run writes `today.md`, email its full contents to the configured recipients, once per day, controlled entirely by config.

**Architecture:** A new self-contained `scripts/email_schedule.py` holds all logic (config resolution, once-per-day stamp, message build, SMTP send with O365→Gmail fallback). `scripts/generate-daily-files.py` calls one function (`maybe_send`) right after writing `today.md`. Email is best-effort and never breaks file generation.

**Tech Stack:** Python ≥3.10 stdlib (`smtplib`, `email.message`, `subprocess`), optional `markdown` for HTML, macOS `security` CLI for Keychain, `pyyaml` config.

## Global Constraints

- **Best-effort:** an email failure must NEVER break `today.md` generation. All email work runs after the file is written, inside try/except.
- **No plaintext secrets:** SMTP app passwords come from the macOS Keychain via `security find-generic-password`. Never read from or written to config/files.
- **Config-driven only:** enabled by `integrations.email_scheduled: true`. No CLI flag, no launchd plist change.
- **Once per day:** send only if `<tasks_root>/.schedule-email-sent` does not already contain today's date; write that stamp only after a successful send.
- **Recipients:** `integrations.emails` (a list). **Primary from:** `email_from` via `smtp.office365.com:587`. **Fallback:** `email_fallback_from` via `smtp.gmail.com:587`.
- **Keychain service:** default `task-management-smtp`; the Keychain *account* is the sending address (`email_from` / `email_fallback_from`).
- **Follow repo patterns:** config read via `config.get_config()`; tests use `pytest` + `unittest.mock`, with `sys.path.insert(0, scripts)` (mirror `tests/test_calendar_apple.py`).
- **Commits:** end every commit message with the `Co-Authored-By:` and `Claude-Session:` trailers (per environment).
- Run the full suite with `python3 -m pytest tests/ -q` from the repo root.

## File Structure

- **Create** `scripts/email_schedule.py` — all email logic (pure functions; takes a config dict).
- **Create** `tests/test_email_schedule.py` — unit tests (mock SMTP, Keychain, stamp file).
- **Modify** `scripts/generate-daily-files.py` — import `email_schedule` + `get_config`; one-line hook after the `today.md` write.
- **Modify** `config/config.template.yaml` — new `integrations` keys (commented).
- **Modify** `pyproject.toml` — add `markdown` dependency.

---

### Task 1: Keychain password reader

**Files:**
- Create: `scripts/email_schedule.py`
- Test: `tests/test_email_schedule.py`

**Interfaces:**
- Produces: `get_keychain_password(service: str, account: str) -> str | None`

- [ ] **Step 1: Write the failing test**

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_email_schedule.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'email_schedule'`

- [ ] **Step 3: Write minimal implementation**

Create `scripts/email_schedule.py`:

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_email_schedule.py -q`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add scripts/email_schedule.py tests/test_email_schedule.py
git commit -m "Add Keychain password reader for schedule email"
```

---

### Task 2: Config resolver

**Files:**
- Modify: `scripts/email_schedule.py`
- Test: `tests/test_email_schedule.py`

**Interfaces:**
- Produces: `load_email_config(config: dict) -> dict | None` — returns `None` when `integrations.email_scheduled` is falsy; else a dict with keys `recipients: list[str]`, `service: str`, `primary: {from,host,port}`, `fallback: {from,host,port}`.

- [ ] **Step 1: Write the failing test**

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_email_schedule.py -q`
Expected: FAIL — `AttributeError: module 'email_schedule' has no attribute 'load_email_config'`

- [ ] **Step 3: Write minimal implementation**

Append to `scripts/email_schedule.py`:

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_email_schedule.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add scripts/email_schedule.py tests/test_email_schedule.py
git commit -m "Add email config resolver"
```

---

### Task 3: Once-per-day stamp guard

**Files:**
- Modify: `scripts/email_schedule.py`
- Test: `tests/test_email_schedule.py`

**Interfaces:**
- Produces: `should_send_today(config: dict, today_str: str) -> bool`, `mark_sent_today(config: dict, today_str: str) -> None`. Stamp file is `<config["paths"]["tasks_root"]>/.schedule-email-sent`.

- [ ] **Step 1: Write the failing test**

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_email_schedule.py -q`
Expected: FAIL — `AttributeError: ... 'should_send_today'`

- [ ] **Step 3: Write minimal implementation**

Append to `scripts/email_schedule.py`:

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_email_schedule.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add scripts/email_schedule.py tests/test_email_schedule.py
git commit -m "Add once-per-day stamp guard for schedule email"
```

---

### Task 4: Message builder (text + HTML)

**Files:**
- Modify: `scripts/email_schedule.py`
- Modify: `pyproject.toml`
- Test: `tests/test_email_schedule.py`

**Interfaces:**
- Produces: `build_message(markdown_text: str, subject: str, sender: str, recipients: list[str]) -> email.message.EmailMessage` — `multipart/alternative` with a `text/plain` part (raw markdown) and, when the `markdown` lib imports, a `text/html` part.

- [ ] **Step 1: Add the `markdown` dependency and install it**

Edit `pyproject.toml`: change `dependencies = ["pyyaml"]` to:

```toml
dependencies = ["pyyaml", "markdown"]
```

Then install into the interpreter that runs the tests and the launchd job:

Run: `python3 -m pip install markdown`
Expected: `Successfully installed markdown-...`

- [ ] **Step 2: Write the failing test**

```python
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
```

- [ ] **Step 3: Run test to verify it fails**

Run: `python3 -m pytest tests/test_email_schedule.py -q`
Expected: FAIL — `AttributeError: ... 'build_message'`

- [ ] **Step 4: Write minimal implementation**

Append to `scripts/email_schedule.py`:

```python
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
```

- [ ] **Step 5: Run test to verify it passes**

Run: `python3 -m pytest tests/test_email_schedule.py -q`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add scripts/email_schedule.py tests/test_email_schedule.py pyproject.toml
git commit -m "Add multipart text+HTML message builder; add markdown dep"
```

---

### Task 5: SMTP sender

**Files:**
- Modify: `scripts/email_schedule.py`
- Test: `tests/test_email_schedule.py`

**Interfaces:**
- Produces: `send_via_smtp(host: str, port: int, user: str, password: str, message) -> None` — connects with STARTTLS, logs in, sends. Raises on failure.

- [ ] **Step 1: Write the failing test**

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_email_schedule.py -q`
Expected: FAIL — `AttributeError: ... 'send_via_smtp'`

- [ ] **Step 3: Write minimal implementation**

Append to `scripts/email_schedule.py`:

```python
def send_via_smtp(host, port, user, password, message):
    """Send message via SMTP + STARTTLS. Raises on failure."""
    with smtplib.SMTP(host, port, timeout=30) as smtp:
        smtp.starttls()
        smtp.login(user, password)
        smtp.send_message(message)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_email_schedule.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add scripts/email_schedule.py tests/test_email_schedule.py
git commit -m "Add SMTP+STARTTLS sender"
```

---

### Task 6: Send orchestrator with fallback

**Files:**
- Modify: `scripts/email_schedule.py`
- Test: `tests/test_email_schedule.py`

**Interfaces:**
- Consumes: `get_keychain_password`, `build_message`, `send_via_smtp`.
- Produces: `send_schedule_email(markdown_text: str, today_str: str, cfg: dict) -> bool` — computes subject `Schedule for <a b d>`, tries `primary` then `fallback`; for each leg skips if no `from`/`host` or no Keychain password; returns True on first success, False if all fail. Never raises.

- [ ] **Step 1: Write the failing test**

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_email_schedule.py -q`
Expected: FAIL — `AttributeError: ... 'send_schedule_email'`

- [ ] **Step 3: Write minimal implementation**

Append to `scripts/email_schedule.py`:

```python
def send_schedule_email(markdown_text, today_str, cfg):
    """Send via primary (O365), falling back to Gmail. Returns True on success; never raises."""
    try:
        date_label = datetime.strptime(today_str, "%Y-%m-%d").strftime("%a %b %-d")
    except ValueError:
        date_label = today_str
    subject = f"Schedule for {date_label}"

    recipients = cfg.get("recipients") or []
    if not recipients:
        print("email_schedule: no recipients configured; skipping", file=sys.stderr)
        return False

    for which in ("primary", "fallback"):
        leg = cfg.get(which) or {}
        sender = leg.get("from")
        host = leg.get("host")
        port = leg.get("port")
        if not sender or not host:
            continue
        password = get_keychain_password(cfg["service"], sender)
        if not password:
            print(f"email_schedule: no keychain password for {sender} ({which})", file=sys.stderr)
            continue
        message = build_message(markdown_text, subject, sender, recipients)
        try:
            send_via_smtp(host, port, sender, password, message)
            print(f"email_schedule: sent via {which} ({sender})", file=sys.stderr)
            return True
        except (smtplib.SMTPException, OSError) as e:
            print(f"email_schedule: {which} send failed ({sender}): {e}", file=sys.stderr)
            continue

    print("email_schedule: all send attempts failed", file=sys.stderr)
    return False
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_email_schedule.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add scripts/email_schedule.py tests/test_email_schedule.py
git commit -m "Add send orchestrator with O365->Gmail fallback"
```

---

### Task 7: Top-level `maybe_send`

**Files:**
- Modify: `scripts/email_schedule.py`
- Test: `tests/test_email_schedule.py`

**Interfaces:**
- Consumes: `load_email_config`, `should_send_today`, `send_schedule_email`, `mark_sent_today`.
- Produces: `maybe_send(config: dict, today_str: str, today_md_path) -> str` — returns one of `"disabled"`, `"skipped (already sent today)"`, `"sent"`, `"failed (see log)"`, or `"skipped (<error>)"`. Stamps only on success. Never raises.

- [ ] **Step 1: Write the failing test**

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_email_schedule.py -q`
Expected: FAIL — `AttributeError: ... 'maybe_send'`

- [ ] **Step 3: Write minimal implementation**

Append to `scripts/email_schedule.py`:

```python
def maybe_send(config, today_str, today_md_path):
    """Gate on config + once-per-day stamp, send, stamp on success. Returns a status string."""
    try:
        cfg = load_email_config(config)
        if cfg is None:
            return "disabled"
        if not should_send_today(config, today_str):
            return "skipped (already sent today)"
        text = Path(today_md_path).read_text()
        if send_schedule_email(text, today_str, cfg):
            mark_sent_today(config, today_str)
            return "sent"
        return "failed (see log)"
    except Exception as e:  # never break generation
        return f"skipped ({e})"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_email_schedule.py -q`
Expected: PASS (all email_schedule tests green)

- [ ] **Step 5: Commit**

```bash
git add scripts/email_schedule.py tests/test_email_schedule.py
git commit -m "Add maybe_send top-level orchestration"
```

---

### Task 8: Wire into the generator + config template

**Files:**
- Modify: `scripts/generate-daily-files.py` (imports + hook after the `today.md` write)
- Modify: `config/config.template.yaml` (new `integrations` keys)

**Interfaces:**
- Consumes: `email_schedule.maybe_send`, `config.get_config`.

- [ ] **Step 1: Add `get_config` to the config import**

In `scripts/generate-daily-files.py`, change the `from config import (...)` block to also import `get_config`:

```python
from config import (
    get_tasks_root, get_folder, get_link_format, get_config,
    is_apple_calendar_enabled, get_apple_calendar_calendars,
    is_podcast_digest_enabled, get_podcast_digest_path,
    get_podcast_digest_refresh_cmd,
)
```

- [ ] **Step 2: Add the optional `email_schedule` import**

Directly below the existing `calendar_apple` optional import block, add:

```python
try:
    import email_schedule
except ImportError:
    email_schedule = None
```

- [ ] **Step 3: Add the hook after `today.md` is written**

In `generate_today_md`, immediately after the block that writes the file:

```python
    with open(BASE_DIR / "today.md", 'w') as f:
        f.write(content)
```

insert:

```python
    if email_schedule is not None:
        status = email_schedule.maybe_send(get_config(), today, BASE_DIR / "today.md")
        print(f"  - schedule email: {status}")
```

(`today` is `dates['today']`, already bound near the top of `generate_today_md`.)

- [ ] **Step 4: Add config keys to the template**

In `config/config.template.yaml`, under `integrations:` (after the `podcast_digest` lines), add:

```yaml
  email_scheduled: false                # email today.md once per day (config-driven)
  # emails: ["matt@shapeandship.com"]   # recipient list
  # email_from: "matt@shapeandship.com"
  # email_smtp_host: "smtp.office365.com"
  # email_smtp_port: 587
  # email_keychain_service: "task-management-smtp"
  # Fallback (used only if the primary SMTP send fails):
  # email_fallback_from: "mbjornson@gmail.com"
  # email_fallback_smtp_host: "smtp.gmail.com"
  # email_fallback_smtp_port: 587
```

- [ ] **Step 5: Verify syntax + template + full suite**

Run: `python3 -c "import ast; ast.parse(open('scripts/generate-daily-files.py').read()); print('generator parses')"`
Expected: `generator parses`

Run: `python3 -c "import yaml; yaml.safe_load(open('config/config.template.yaml')); print('template valid')"`
Expected: `template valid`

Run: `python3 -m pytest tests/ -q`
Expected: all pass (existing 87 + the new email tests)

- [ ] **Step 6: Commit**

```bash
git add scripts/generate-daily-files.py config/config.template.yaml
git commit -m "Wire schedule email into the daily generator + config template"
```

---

### Task 9: Docs + real send verification

**Files:**
- Modify: `README.md` (document the email integration + setup)

- [ ] **Step 1: Document the feature in README**

Add a short section after the Apple Calendar / podcast integration docs describing: `integrations.email_scheduled` + `emails`, the O365→Gmail fallback, the Keychain setup commands (from the spec), and that it sends once per day on the first generation (normally the 6am launchd run). Keep it factual and concise.

- [ ] **Step 2: Commit the docs**

```bash
git add README.md
git commit -m "Document the schedule-email integration"
```

- [ ] **Step 3: Real send verification (manual; requires user secrets)**

> This step requires the user to have created the app password(s) and stored them in Keychain, and to have set `email_scheduled: true` + `emails`/`email_from` in `~/.claude/task-management-config/config.yaml`.

Run a one-off send using the real config (does not depend on launchd):

```bash
cd /Users/matt/Projects/task-management
python3 -c "
import sys; sys.path.insert(0,'scripts')
import email_schedule
from config import get_config, get_tasks_root
cfg = get_config()
# Force-send regardless of today's stamp for this test:
print('config enabled:', email_schedule.load_email_config(cfg) is not None)
text = (get_tasks_root() / 'today.md').read_text()
print('send result:', email_schedule.send_schedule_email(text, '$(date +%F)', email_schedule.load_email_config(cfg)))
"
```
Expected: `send result: True`, and the email arrives at the configured recipients. The stderr line reports which leg sent (`primary` O365 or `fallback` Gmail). If `False`, read `~/Library/Logs/task-management.log` / the stderr lines to see whether O365 SMTP AUTH was refused (then the Gmail fallback must be configured).

---

## Self-Review

**Spec coverage:**
- Full today.md emailed → Task 4 (build) + Task 6/7 (send) + Task 8 (reads `today.md`). ✓
- Config-driven, no flag/plist → Task 8 hook gated by `load_email_config`; no `--email`. ✓
- Once per day → Task 3 stamp + Task 7. ✓
- O365 primary, Gmail fallback → Task 6. ✓
- Text + HTML body → Task 4. ✓
- Subject with date → Task 6 (`Schedule for <a b d>`). ✓
- Best-effort, never breaks generation → Task 7 try/except + Task 8 guarded hook. ✓
- Secrets in Keychain → Task 1, used in Task 6. ✓
- Config keys (`email_scheduled`, `emails`, from/SMTP, fallback) → Task 8 template; resolver Task 2. ✓
- `markdown` dependency → Task 4. ✓
- Tests for build/send/fallback/stamp/keychain/maybe_send → Tasks 1–7. ✓
- Real verification → Task 9. ✓

**Placeholder scan:** No TBD/TODO; every code step has complete code; commands have expected output. ✓

**Type consistency:** `should_send_today`/`mark_sent_today` take `(config, today_str)` consistently (Tasks 3, 7). `send_via_smtp(host, port, user, password, message)` positional order matches the call in Task 6 and the assertion in Task 5. `load_email_config` keys (`recipients`, `service`, `primary/fallback.{from,host,port}`) match consumption in Task 6. `maybe_send(config, today_str, today_md_path)` matches the Task 8 call. ✓

> **Note vs spec:** the stamp helpers take `today_str` explicitly (the spec wrote `should_send_today(config)`); this is a minor, intentional refinement for testability and does not change behavior.
