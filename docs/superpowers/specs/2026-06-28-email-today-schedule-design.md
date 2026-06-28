# Design: Email today's schedule

- **Date:** 2026-06-28
- **Status:** Approved
- **Branch:** `feat/email-daily-schedule`

## Goal

After the daily run generates `today.md`, email the full contents to the user
(`matt@shapeandship.com`) so the day's schedule arrives in the inbox each morning.

## Context

- `scripts/generate-daily-files.py` writes `today.md` (sections: Overdue, Due
  Today, Meetings, Podcast Digest, Ideas, Research). The Meetings section now
  comes from EventKit (see the calendar-EventKit work).
- A launchd agent `~/Library/LaunchAgents/com.shapeandship.task-management.plist`
  runs the generator daily at 06:00 using `~/.pyenv/versions/3.14.0/bin/python3`.
- The same generator also runs interactively (via the `/today` skill and CLI).
- Accounts available: Microsoft 365 (`matt@shapeandship.com`, primary) and three
  Google accounts. The user's mailbox is M365.

## Requirements

### Functional
1. Email the **full** `today.md` to `matt@shapeandship.com`.
2. Send **only** on the scheduled 06:00 run — never on interactive `/today`/CLI runs.
3. Send **from** `matt@shapeandship.com` via O365 SMTP when possible.
4. If O365 SMTP auth/connection fails, **fall back** to sending via a Gmail app
   password (`mbjornson@gmail.com`) — still delivered to `matt@shapeandship.com`.
5. Email body: plain-text (raw markdown) + HTML (rendered) alternatives.
6. Subject line includes the date, e.g. `Schedule for Mon Jun 30`.

### Non-functional
- **Best-effort:** an email failure must never break `today.md` generation
  (the file is written before any send is attempted).
- **No plaintext secrets:** app passwords live in the macOS Keychain.
- **macOS-only / no-op elsewhere** and when disabled or run without `--email`.
- Self-contained: email logic isolated in its own module with a small interface.

## Design

### Trigger: `--email` flag + config toggle
- `generate-daily-files.py` gains a `--email` flag. The launchd plist adds
  `--email` to its `ProgramArguments`; interactive runs omit it, so they never email.
- Sending also requires `integrations.email_schedule: true` in config. Both the
  flag **and** the toggle must be present to send. This double-gate prevents
  accidental sends and keeps config the source of truth for recipients/SMTP.
- No idempotency stamp: launchd `StartCalendarInterval` fires once per day; a
  manual `--email` run is an explicit user choice. (YAGNI.)

### New module: `scripts/email_schedule.py`
Single purpose: render and send the schedule email. Public interface:

- `load_email_config(config: dict) -> dict | None`
  Returns the resolved email settings from `integrations`, or `None` if
  `email_schedule` is not enabled.
- `get_keychain_password(service: str, account: str) -> str | None`
  Reads a generic password via `security find-generic-password -s <service> -a <account> -w`.
  Returns `None` (not crash) if absent.
- `build_message(markdown_text: str, subject: str, sender: str, recipient: str) -> EmailMessage`
  Builds a `multipart/alternative` message: plain-text part = raw markdown;
  HTML part = `markdown.markdown(markdown_text)` if the `markdown` lib imports,
  otherwise text-only.
- `send_via_smtp(host, port, user, password, message) -> None`
  `smtplib.SMTP(host, port)` → `starttls()` → `login()` → `send_message()`.
  Raises on failure (caller decides fallback).
- `send_schedule_email(markdown_text: str, today_str: str, cfg: dict) -> bool`
  Orchestrator. Builds the message; tries primary (O365); on
  `smtplib.SMTPException`/`OSError` tries the fallback (Gmail) if configured;
  logs which path succeeded or that both failed. Returns success bool. Never raises.

### Integration hook
In `generate-daily-files.py`, after `today.md` is written:
```
email_cfg = email_schedule.load_email_config(config)  # None unless enabled
if args.email and email_cfg:
    try:
        text = (BASE_DIR / "today.md").read_text()
        ok = email_schedule.send_schedule_email(text, today_str, email_cfg)
        print(f"  - schedule email: {'sent' if ok else 'failed (see log)'}")
    except Exception as e:
        print(f"  - schedule email skipped: {e}")
```
The hook is wrapped so it can never abort generation.

### Sending details
- Primary: `smtp.office365.com:587`, STARTTLS, `From/To = matt@shapeandship.com`,
  password from Keychain (`service=task-management-smtp`, `account=matt@shapeandship.com`).
- Fallback: `smtp.gmail.com:587`, STARTTLS, login `mbjornson@gmail.com` (Keychain
  `account=mbjornson@gmail.com`), `From=mbjornson@gmail.com`, `To=matt@shapeandship.com`.
- Both 587/STARTTLS for consistency.

### Secrets (macOS Keychain)
```
security add-generic-password -U -s task-management-smtp -a matt@shapeandship.com -w '<o365-app-pw>'
security add-generic-password -U -s task-management-smtp -a mbjornson@gmail.com   -w '<gmail-app-pw>'
```
Read with `security find-generic-password -s task-management-smtp -a <acct> -w`.
The launchd run reads the login keychain (unlocked while logged in). The first
read may surface a Keychain access prompt; running the script once interactively
with `--email` lets the user grant "Always Allow".

### Config keys (added to `config.template.yaml` under `integrations:`)
```yaml
  email_schedule: false                 # email today.md (only when run with --email)
  # email_to: "matt@shapeandship.com"
  # email_from: "matt@shapeandship.com"
  # email_smtp_host: "smtp.office365.com"
  # email_smtp_port: 587
  # email_keychain_service: "task-management-smtp"
  # email_keychain_account: "matt@shapeandship.com"
  # Fallback (used only if primary SMTP send fails):
  # email_fallback_from: "mbjornson@gmail.com"
  # email_fallback_smtp_host: "smtp.gmail.com"
  # email_fallback_smtp_port: 587
  # email_fallback_keychain_account: "mbjornson@gmail.com"
```

### Error handling
- File generation always completes; email is attempted afterward inside try/except.
- Primary send raises → fallback attempted (if configured).
- Both fail, or a Keychain password is missing → log a clear line to
  `~/Library/Logs/task-management.log`, return `False`, continue.
- Not macOS / not enabled / no `--email` → no-op.

## Components & interfaces

| Unit | Purpose | Depends on |
|---|---|---|
| `email_schedule.py` | render + send the schedule email | `smtplib`, `email`, `subprocess` (Keychain), optional `markdown`, config dict |
| `generate-daily-files.py` hook | invoke the sender after writing `today.md` when `--email` + enabled | `email_schedule`, config |
| `config.template.yaml` | declare email settings | — |
| launchd plist | pass `--email` on the 06:00 run | — |

## Data flow
launchd 06:00 → `generate-daily-files.py --email` → writes `today.md` →
reads it back → `send_schedule_email` → O365 SMTP (or Gmail fallback) → inbox.

## Dependencies
- Add `markdown` to `pyproject.toml` (`[project].dependencies`) for HTML rendering;
  runtime-degrades to text-only if the import fails.

## Testing
Unit tests (mock `smtplib.SMTP` and the Keychain `security` subprocess):
- `build_message` produces a `multipart/alternative` with correct subject/from/to
  and both text and HTML parts.
- `send_via_smtp` calls `starttls`, `login`, `send_message` in order.
- `send_schedule_email`: primary success path; primary raises
  `SMTPAuthenticationError` → fallback attempted and succeeds; both fail → `False`
  and an error is logged; never raises.
- Missing Keychain password → handled (skip/fallback), no crash.
- Generator hook: `--email` absent or integration disabled → sender not called.
Real verification: one manual `--email` run after secrets are set; confirm the
email arrives at `matt@shapeandship.com` and which path (O365 vs Gmail) was used.

## Manual prerequisites (user)
1. Create an O365 app password for `matt@shapeandship.com` (Microsoft account
   security) and/or a Gmail app password for `mbjornson@gmail.com`.
2. Store them in Keychain with the commands above.
3. Set `integrations.email_schedule: true` (and recipient/SMTP keys) in config.

## Out of scope (YAGNI)
- Changing the schedule (reuse the existing 06:00 launchd job).
- HTML theming/branding, attachments, multiple recipients.
- O365 OAuth2/Graph (only pursued if both SMTP paths prove unworkable).
