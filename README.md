# task-management

A Claude Code plugin for markdown-based task management. Generates daily/weekly task views, archives completed tasks, and tracks ideas. This was forked from teresa-torres-plugins/task-management. 

## Installation

```bash
# Add this repo as a plugin marketplace, then install the plugin from it
claude plugin marketplace add mbjornson/task-management
claude plugin install task-management@mbjornson
```

`mbjornson/task-management` is the GitHub `owner/repo`; the `@mbjornson` suffix is the marketplace **name** defined in `.claude-plugin/marketplace.json` (see [Publishing to a marketplace](#publishing-to-a-marketplace)). Inside an active Claude Code session, use the slash-command equivalents `/plugin marketplace add mbjornson/task-management` and `/plugin install task-management@mbjornson`.

After installation, run the setup wizard:

```
/task-management:setup
```

## Configuration

Configuration is stored in `~/.claude/task-management-config/config.yaml`:

```yaml
paths:
  tasks_root: "/path/to/your/Tasks"

folders:
  tasks: "tasks"
  ideas: "ideas"
  templates: "templates"
  memories: "memories"
  bugs: "bugs"
  completed: "completed"
  import: "import"

links:
  format: "obsidian"       # "obsidian" for [[wiki-links]] or "markdown" for [text](path)

integrations:
  research_system: false   # Set to true to include research digest in /today
  apple_calendar: false    # Set to true to include today's Apple Calendar meetings in /today
  podcast_digest: false    # Set to true to include today's podcast digest in /today
  # podcast_digest_path: "/path/to/ai-podcast-ripper/transcripts/digests"          # Directory of YYYY-MM-DD.md digest files
  # podcast_digest_refresh_cmd: "/path/to/python3 /path/to/ai-podcast-ripper/rip.py --digest"  # Optional: materialize today's digest on demand before reading
```

### Link Format

The plugin supports two link formats:

- **obsidian** (default) - Wiki-style links: `[[task-name]]`
- **markdown** - Standard markdown links: `[task-name](tasks/task-name.md)`

Choose "obsidian" if you use Obsidian or another wiki-link aware editor. Choose "markdown" for standard markdown compatibility.

### Research System Integration

If you have the `research-system` plugin installed and want `/today` to include a research digest section, set `integrations.research_system: true`.

### Apple Calendar Integration

When `integrations.apple_calendar` is `true`, the script fills the **Meetings** section of today.md with today's events from Apple Calendar every time `generate-daily-files.py` runs (e.g. via `/task-management:today`, cron, or CLI). By default **all** calendars are queried so no events are missed. On macOS it reads Calendar.app directly via native **EventKit** (PyObjC) — the same API the [mcp-ical](https://github.com/Omar-V2/mcp-ical) server uses — which sees every calendar and maps each event independently, so a single malformed event can never silently drop the rest. If PyObjC isn't installed or Calendar permission is denied, it falls back to a hardened AppleScript reader (each event is read in its own `try`/`on error`, so one bad event is skipped rather than abandoning its calendar). Grant Calendar access to Terminal (or the process running the script) if prompted; on macOS install the EventKit binding with `pip install pyobjc-framework-EventKit`. Optional: set `integrations.apple_calendar_calendars` to a list of calendar names to limit which calendars are queried. The **Apple Calendar MCP** (mcp-ical; install with `/task-management:install-apple-calendar-mcp`) is optional and only for using calendar tools from an MCP client — the plugin's Meetings section does not depend on it.

### Podcast Digest Integration

When `integrations.podcast_digest` is `true`, `/today` adds a **Podcast Digest** section to today.md summarizing the podcasts you listened to (or had transcribed) today. The digests are produced by the companion [**ai-podcast-ripper**](https://github.com/mbjornson/ai-podcast-ripper) project — a local pipeline that fetches new episodes from your RSS feeds, transcribes them with Faster Whisper, summarizes them with a local LLM via Ollama, and writes one `YYYY-MM-DD.md` digest file per day. It runs entirely locally, with no external APIs, and is **not** a Claude Code plugin — it's a separate tool you run on a schedule (e.g. a nightly launchd/cron job).

Point the plugin at the ripper's digest output directory:

```yaml
integrations:
  podcast_digest: true
  podcast_digest_path: "/path/to/ai-podcast-ripper/transcripts/digests"
  # Optional — see below
  podcast_digest_refresh_cmd: "/path/to/python3 /path/to/ai-podcast-ripper/rip.py --digest"
```

Behavior:

- **Today only.** Only today's `YYYY-MM-DD.md` digest is used — it never falls back to an older day's digest, so `/today` always reflects today's episodes (never yesterday's).
- **On-demand refresh (optional).** The ripper writes its digest file at the end of its run, so a long overnight rip may not have today's file ready when you run `/today` in the morning. If `podcast_digest_refresh_cmd` is set, the plugin runs it first to materialize today's digest from already-completed episodes — the ripper's `rip.py --digest` rebuilds the day's digest from its per-episode metrics without re-transcribing anything. This is best-effort: failures are ignored so `/today` still renders.
- **Not-ready placeholder.** If today's digest still isn't available, the section shows `Today's digest not ready yet.` rather than omitting it or showing stale content.

Each episode renders its title, summary, and any action items (as checkable tasks).

### Schedule Email Integration

When `integrations.email_scheduled` is `true`, the generator emails the full contents of `today.md` to the configured recipients. macOS-only.

Configure in `~/.claude/task-management-config/config.yaml`:

```yaml
integrations:
  email_scheduled: true
  emails: ["you@example.com"]              # recipient list
  email_from: "you@example.com"            # sending address (primary)
  # email_smtp_host: "smtp.office365.com"  # default
  # email_smtp_port: 587                   # default
  # email_keychain_service: "task-management-smtp"  # default
  # Fallback — used only if the primary send fails:
  # email_fallback_from: "backup@gmail.com"
  # email_fallback_smtp_host: "smtp.gmail.com"
  # email_fallback_smtp_port: 587
```

SMTP app passwords must be stored in the macOS Keychain (service `task-management-smtp`, account = the sending address):

```bash
security add-generic-password -U -s task-management-smtp -a you@example.com  -w
security add-generic-password -U -s task-management-smtp -a backup@gmail.com -w
```

Omitting the password value after `-w` causes `security` to prompt interactively, keeping the app password out of shell history.

Behavior:

- **Once per day.** A `.schedule-email-sent` stamp in the tasks root records the date of the last successful send. The first generation of the day sends (normally the 6am launchd run); later runs that day are no-ops. A failed send does not write the stamp, so the next run retries.
- **O365 → Gmail fallback.** Primary is `smtp.office365.com:587` (STARTTLS); if that fails and `email_fallback_from` is configured with a Keychain password, the generator retries via `smtp.gmail.com:587`. Both legs send to the same recipient list.
- **Best-effort.** Email failures are logged but never abort `today.md` generation. The email subject is `Schedule for <Day Mon D>` (e.g. `Schedule for Sun Jun 28`).
- **First-run Keychain prompt.** The launchd job reads the login keychain (unlocked while logged in). Run the generator once interactively first to grant "Always Allow" if prompted.

## Commands

### `/task-management:setup`

Interactive setup wizard to configure your tasks root folder and directory structure.

### `/task-management:install-apple-calendar-mcp`

Install the [mcp-ical](https://github.com/Omar-V2/mcp-ical) Apple Calendar MCP server into your MCP config so your MCP client can read and manage your calendar. mcp-ical is native EventKit (PyObjC), macOS-only, and needs `uv` — the installer clones it to `~/.mcp-servers/mcp-ical` and runs `uv sync`. Its tools are `list_events(start_date, end_date, calendar_name?)`, `list_calendars`, and event create/update/delete/search (no `get_today_events`/`get_calendar_events`). Does not assume Cursor: use `MCP_CONFIG_PATH` or `--path` to choose the config file; use `--print-only` to print the JSON and clone/sync commands without writing. After installing, reload MCP and launch the client from a terminal/app that has Calendar permission. This is optional — the plugin's Meetings section reads the calendar directly and does not require this server.

### `/task-management:today`

Generate daily task files:
- `today.md` - Overdue tasks, tasks due today, meetings (from Apple Calendar when enabled), podcast digest (from ai-podcast-ripper when enabled), in-progress ideas
- `this-week.md` - Tasks for remaining days this week
- `next-week.md` - Tasks for next week

Also archives completed tasks and normalizes date formats.

### `/task-management:this-week`

Generate this week's task list (excluding today).

### `/task-management:next-week`

Generate next week's task list.

### `/task-management:archive`

Move completed one-time tasks from `tasks/` to `completed/`. Recurring tasks are never archived.

### `/task-management:ideas`

List ideas organized by status:
- In Progress - Actively working on
- Noodling - Exploring, might become in-progress

### `/task-management:clean-imports`

Move reviewed files from `import/` to their appropriate folders based on `type:` field.

### `/task-management:about`

Show this documentation.

## Skills

### `manage-tasks`

Task conventions and file organization rules. Claude uses this skill when creating or modifying task files to ensure consistent formatting.

To get Claude to reliably use this skill, try putting the following in your Tasks root directory CLAUDE.md: "Use the manage-tasks skill whenever creating or updating tasks."

## File Structure

The plugin expects this folder structure in your tasks root:

```
Tasks/
├── tasks/          # Items with due dates
├── ideas/          # Projects without due dates
├── templates/      # Reusable task templates
├── memories/       # Reference items (not actionable)
├── bugs/           # Issues to fix
├── completed/      # Archived one-time tasks
├── import/         # Staging area for triage
├── today.md        # Generated daily
├── this-week.md    # Generated daily
└── next-week.md    # Generated daily
```

## Task File Format

Each task is a markdown file with YAML frontmatter:

```yaml
---
type: task
due: 2025-01-15
tags: [project, urgent]
---
# Task Title

Task content here.
```

### Fields

**Required:**
- `type` - task, idea, template, memory, or bug

**Optional:**
- `due: YYYY-MM-DD` - Due date (required for tasks)
- `completed: YYYY-MM-DD` - Completion date
- `recurrence: weekly | biweekly | monthly | quarterly | yearly`
- `status: in-progress | noodling | someday` - For ideas only
- `tags: [tag1, tag2]` - Categorization

## Publishing to a marketplace

This repo ships a plugin manifest (`.claude-plugin/plugin.json`), but a plugin only becomes installable when it is **listed in a marketplace**. A marketplace is just a git repo containing a `.claude-plugin/marketplace.json` catalog. One repo can act as both the marketplace **and** the plugin source — which is how this repo is set up.

### 1. Add the marketplace catalog

Create `.claude-plugin/marketplace.json` at the repo root:

```json
{
  "name": "mbjornson",
  "owner": {
    "name": "mbjornson"
  },
  "plugins": [
    {
      "name": "task-management",
      "source": "./",
      "description": "Markdown-based task management with daily/weekly views, archiving, and idea tracking"
    }
  ]
}
```

- `name` is the marketplace identifier users reference as `@mbjornson` when installing. It does **not** have to match the GitHub owner — keep it stable, because changing it breaks existing installs.
- `source: "./"` points at the repo root, where this plugin's `.claude-plugin/plugin.json` lives. For a multi-plugin marketplace, give each entry its own subdirectory path (e.g. `"./plugins/task-management"`) or a `{ "source": "github", "repo": "owner/repo" }` object.

### 2. Publish

Commit and push to the default branch on GitHub:

```bash
git add .claude-plugin/marketplace.json
git commit -m "Add marketplace catalog"
git push
```

The plugin is now installable by anyone using the [Installation](#installation) commands above.

### 3. Shipping updates

Bump `version` in `.claude-plugin/plugin.json` and push. End users pull the new version with:

```bash
claude plugin marketplace update mbjornson
```

Because `plugin.json` sets an explicit `version`, users only receive an update when that field changes. (If `version` were omitted, every pushed commit would count as a new version.)

## License

MIT
