---
description: Generate today.md, this-week.md, and next-week.md files
---

# today

Generate today.md, this-week.md, and next-week.md files.

## Process

### Step 1: Generate Daily Task Files

Run the generate-daily-files.py script:

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/generate-daily-files.py
```

This script will:
1. Normalize dates in all task files
2. Calculate current week and next week dates
3. Archive completed tasks (move to completed/ folder)
4. Grep for tasks by specific dates
5. Generate all three files (today.md, this-week.md, next-week.md)

When `integrations.apple_calendar` is `true`, the script fetches today's events from Apple Calendar and writes the **## Meetings** section (after Due Today, before In Progress Ideas). On macOS, AppleScript is the primary source—it queries every calendar and returns start/end times. The Apple Calendar MCP server is used only as a fallback (non-macOS, or when AppleScript finds nothing), because it sees only a subset of calendars. This happens every time the script runs—whether from `/today`, cron, or the command line.

When `integrations.podcast_digest` is `true` and `integrations.podcast_digest_path` points to a directory containing `yyyy-mm-dd.md` digest files, the script writes a **## Podcast Digest** section (after Meetings, before In Progress Ideas) with podcast names, episode titles, and summaries. Only **today's** digest is used—it never falls back to an older day's. If `integrations.podcast_digest_refresh_cmd` is set, the script runs it first to materialize today's digest on demand (e.g. the ripper's `rip.py --digest`, which rebuilds today's digest from already-completed episodes) so you see today's episodes-so-far rather than waiting for the full rip. If today's digest still isn't available, the section shows **Today's digest not ready yet.** instead.

### Step 2: Generate Research Digest (Optional)

**Only if `integrations.research_system` is `true` in `~/.claude/task-management-config/config.yaml`:**

1. Run the research digest slash command:
   ```
   SlashCommand: /research-system:generate-research-digest
   ```

2. Add a Research section to today.md (after "In Progress Ideas" section) using the `links.format` setting from config.

## Example Output - today.md

```markdown
---
date: 2025-10-03
---
# Today - Thursday, October 3

## Overdue
- [ ] [[old-task]] (due: 2025-09-30)
- [ ] [[another-overdue]] (due: 2025-10-01)

## Due Today
- [ ] [[give-dog-flea-medicine]]
- [ ] [[bbc-sale]]
- [ ] [[schedule-grooming-loosa]]

## Meetings
- 9:00:00 AM–9:30:00 AM Standup
- 2:00:00 PM–3:00:00 PM Client call

## Podcast Digest
### Lenny's Podcast
**The art of influence: The single most important skill...**
Summary paragraph from the episode digest.

## In Progress Ideas
- [[next-ai-project]]
- [[course-redesign]]

## Research
- [ ] [Review today's research digest](Research/research-today.md)
```

## Example Output - this-week.md

```markdown
---
week_start: 2025-10-04
week_end: 2025-10-06
---
# This Week - Week ending October 6

## Friday, October 4
- [ ] [[client-meeting]]

## Saturday, October 5
- [ ] [[weekly-review]]
```

## Example Output - next-week.md

```markdown
---
week_start: 2025-10-07
week_end: 2025-10-13
---
# Next Week - Week of October 7

## Monday, October 7
- [ ] [[quarterly-planning]]

## Wednesday, October 9
- [ ] [[team-sync]]
```
