# task-management

A Claude Code plugin for markdown-based task management. Generates daily/weekly task views, archives completed tasks, and tracks ideas.

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
```

### Link Format

The plugin supports two link formats:

- **obsidian** (default) - Wiki-style links: `[[task-name]]`
- **markdown** - Standard markdown links: `[task-name](tasks/task-name.md)`

Choose "obsidian" if you use Obsidian or another wiki-link aware editor. Choose "markdown" for standard markdown compatibility.

### Research System Integration

If you have the `research-system` plugin installed and want `/today` to include a research digest section, set `integrations.research_system: true`.

### Apple Calendar Integration

When `integrations.apple_calendar` is `true`, the script fills the **Meetings** section of today.md with today's events from Apple Calendar every time `generate-daily-files.py` runs (e.g. via `/task-management:today`, cron, or CLI). By default **all** calendars are queried so no events are missed. On macOS it uses AppleScript to read Calendar.app; grant Calendar access to Terminal (or the process running the script) if prompted. Optional: set `integrations.apple_calendar_calendars` to a list of calendar names to limit which calendars are queried (e.g. to avoid timeouts on very large calendars). The **Apple Calendar MCP** (install with `/task-management:install-apple-calendar-mcp`) is optional and used for other calendar features in Cursor if you want them.

## Commands

### `/task-management:setup`

Interactive setup wizard to configure your tasks root folder and directory structure.

### `/task-management:install-apple-calendar-mcp`

Install the Apple Calendar MCP server into your MCP config so the plugin and your MCP client can use it. Does not assume Cursor: use `MCP_CONFIG_PATH` or `--path` to choose the config file; use `--print-only` to print the JSON and common paths without writing. Run once; then reload MCP and grant Calendar/Full Disk Access on macOS if needed.

### `/task-management:today`

Generate daily task files:
- `today.md` - Overdue tasks, tasks due today, meetings (from Apple Calendar when enabled), in-progress ideas
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
