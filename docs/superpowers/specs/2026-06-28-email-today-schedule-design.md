# Design: Email today's schedule

- **Date:** 2026-06-28
- **Status:** Approved (revised — fully config-driven)
- **Branch:** `feat/email-daily-schedule`

## Goal

After the daily run generates `today.md`, email its full contents to the
recipient(s) configured in `config.yaml` so the day's schedule arrives in the
inbox each morning. Control is entirely via config — no CLI flags, no launchd edits.

## Context

- `scripts/generate-daily-files.py` writes `today.md` (sections: Overdue, Due
  Today, Meetings, Podcast Digest, Ideas, Research). Meetings now come from EventKit.
- A launchd agent `~/Library/LaunchAgents/com.shapeandship.task-management.plist`
  runs the generator daily at 06:00 using `~/.pyenv/versions/3.14.0/bin/python3`.
- The same generator also runs interactively (via the `/today` skill and CLI).
- Accounts available: Microsoft 365 (`matt@shapeandship.com`, primary mailbox) and
  three Google accounts.

## Requirements

### Functional
1. Email the **full** `today.md` to the recipient(s) in `integrations.emails`.
2. **Config-driven only:** enabled by `integrations.email_scheduled: true`. No CLI
   flag and no launchd plist change.
3. Send at most **once per day** — the first generation of the day sends (normally
   the 06:00 launchd run); later runs that day are no-ops. (Prevents manual
   `/today` runs from re-sending.)
4. Send **from** `matt@shapeandship.com` via O365 SMTP when possible.
5. If O365 SMTP auth/connection fails, **fall back** to a Gmail app password
   (`mbjornson@gmail.com`) — still delivered to the configured recipients.
6. Email body: plain-text (raw markdown) + HTML (rendered) alternatives.
7. Subject includes the date, e.g. `Schedule for Mon Jun 30`.

### Non-functional
- **Best-effort:** an email failure must never break `today.md` generation
  (the file is written before any send is attempted).
- **No plaintext secrets:** app passwords live in the macOS Keychain.
- **macOS-only / no-op** when disabled, non-macOS, or already sent today.
- Self-contained: email logic isolated in its own module with a small interface.

## Design

### Trigger: config toggle + once-per-day guard
- Fully config-driven. Sending is enabled by `integrations.email_scheduled: true`.
  The launchd job and `/today` are unchanged.
- Because the generator also runs interactively, a config-only gate would email on
  every run. A once-per-day **stamp** makes it idempotent: the sender records the
  date it last emailed in `<tasks_root>/.schedule-email-sent` (contents `YYYY-MM-DD`)
  and sends only if that date is not today. The first run of the day sends;
  subsequent runs that day are no-ops. The stamp is written only after a successful
  send, so a failed send is retried on the next run.

### New module: `scripts/email_schedule.py`
Single purpose: decide whether to send, then render and send the schedule email.
Public interface:

- `load_email_config(config: dict) -> dict | None`
  Returns resolved email settings from `integrations` (recipients, from, SMTP,
  keychain, fallback), or `None` if `email_scheduled` is not enabled.
- `should_send_today(config: dict) -> bool`
  Returns `False` if `<tasks_root>/.schedule-email-sent` already holds today's date.
- `mark_sent_today(config: dict) -> None`
  Writes today's date to the stamp file.
- `get_keychain_password(service: str, account: str) -> str | None`
  Reads via `security find-generic-password -s <service> -a <account> -w`;
  returns `None` (no crash) if absent.
- `build_message(markdown_text, subject, sender, recipients: list[str]) -> EmailMessage`
  Builds a `multipart/alternative` message: plain-text = raw markdown; HTML =
  `markdown.markdown(markdown_text)` if the `markdown` lib imports, else text-only.
- `send_via_smtp(host, port, user, password, message) -> None`
  `smtplib.SMTP` → `starttls()` → `login()` → `send_message()`. Raises on failure.
- `send_schedule_email(markdown_text, today_str, cfg) -> bool`
  Orchestrator: build message; try primary (O365); on `smtplib.SMTPException`/`OSError`
  try fallback (Gmail) if configured; log which path won or that both failed.
  Returns success bool. Never raises.

### Integration hook
In `generate-daily-files.py`, after `today.md` is written:
```
email_cfg = email_schedule.load_email_config(config)  # None unless email_scheduled
if email_cfg and email_schedule.should_send_today(config):
    try:
        text = (BASE_DIR / "today.md").read_text()
        ok = email_schedule.send_schedule_email(text, today_str, email_cfg)
        if ok:
            email_schedule.mark_sent_today(config)
        print(f"  - schedule email: {'sent' if ok else 'failed (see log)'}")
    except Exception as e:
        print(f"  - schedule email skipped: {e}")
```
The hook is wrapped so it can never abort generation.

### Sending details
- Primary: `smtp.office365.com:587`, STARTTLS, `From = matt@shapeandship.com`,
  password from Keychain (`service=task-management-smtp`, `account=email_from`).
- Fallback: `smtp.gmail.com:587`, STARTTLS, login `mbjornson@gmail.com` (Keychain
  `account=mbjornson@gmail.com`), `From=mbjornson@gmail.com`.
- `To` = the configured `emails` list in both cases. Both use 587/STARTTLS.

### Secrets (macOS Keychain)
```
security add-generic-password -U -s task-management-smtp -a matt@shapeandship.com -w '<o365-app-pw>'
security add-generic-password -U -s task-management-smtp -a mbjornson@gmail.com   -w '<gmail-app-pw>'
```
Read with `security find-generic-password -s task-management-smtp -a <acct> -w`.
The launchd run reads the login keychain (unlocked while logged in). The first
read may surface a Keychain prompt; running the generator once interactively lets
the user grant "Always Allow".

### Config keys (added to `config.template.yaml` under `integrations:`)
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
The Keychain account for the primary is `email_from`; for the fallback it is
`email_fallback_from`.

### Error handling
- File generation always completes; email is attempted afterward inside try/except.
- Primary send raises → fallback attempted (if configured).
- Both fail, or a Keychain password is missing → log a clear line to
  `~/Library/Logs/task-management.log`, return `False`, do **not** write the stamp
  (so the next run retries), continue.
- Disabled / non-macOS / already sent today → no-op.

## Components & interfaces

| Unit | Purpose | Depends on |
|---|---|---|
| `email_schedule.py` | decide-to-send + render + send | `smtplib`, `email`, `subprocess` (Keychain), optional `markdown`, config dict |
| `generate-daily-files.py` hook | invoke the sender after writing `today.md` | `email_schedule`, config |
| `config.template.yaml` | declare email settings | — |
| launchd plist | unchanged (runs the generator at 06:00) | — |

## Data flow
launchd 06:00 → `generate-daily-files.py` → writes `today.md` → if enabled and not
yet sent today → `send_schedule_email` → O365 SMTP (or Gmail fallback) → recipients
→ write stamp.

## Dependencies
- Add `markdown` to `pyproject.toml` (`[project].dependencies`) for HTML rendering;
  runtime-degrades to text-only if the import fails.

## Testing
Unit tests (mock `smtplib.SMTP`, the Keychain `security` subprocess, and the stamp file):
- `build_message`: `multipart/alternative` with correct subject/from/to (list) and
  both text + HTML parts.
- `send_via_smtp`: calls `starttls`, `login`, `send_message` in order.
- `send_schedule_email`: primary success; primary raises `SMTPAuthenticationError`
  → fallback attempted and succeeds; both fail → `False` + logged; never raises.
- `should_send_today`: today already stamped → `False`; absent/older → `True`.
- Stamp written only after a successful send (failed send leaves it unset).
- Missing Keychain password → handled, no crash.
- Hook: `email_scheduled` disabled → sender not called.
Real verification: run the generator once after secrets are set; confirm the email
arrives at the recipients and which path (O365 vs Gmail) was used; confirm a second
run the same day does not re-send.

## Manual prerequisites (user)
1. Create an O365 app password for `matt@shapeandship.com` (Microsoft account
   security) and/or a Gmail app password for `mbjornson@gmail.com`.
2. Store them in Keychain with the commands above.
3. Set `integrations.email_scheduled: true` and `integrations.emails: [...]` (and
   from/SMTP keys) in `config.yaml`.

## Out of scope (YAGNI)
- Changing the schedule (reuse the existing 06:00 launchd job).
- HTML theming/branding, attachments.
- O365 OAuth2/Graph (only if both SMTP paths prove unworkable).
