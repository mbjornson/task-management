#!/usr/bin/env python3
"""
Archive completed one-time tasks from tasks/ to completed/.

Recurring tasks (those with recurrence: field) are never archived.
"""

import re
import shutil
from pathlib import Path

from config import get_folder


def has_frontmatter_field(file_path: Path, field: str) -> bool:
    """Check if a markdown file's YAML frontmatter contains a field."""
    text = file_path.read_text(encoding="utf-8")
    # Match field at start of line within frontmatter (between --- delimiters)
    match = re.search(r"^---\s*\n(.*?)^---\s*\n", text, re.MULTILINE | re.DOTALL)
    if not match:
        return False
    return any(line.startswith(f"{field}:") for line in match.group(1).splitlines())


def archive_completed_tasks():
    """Archive completed one-time tasks to completed/ folder."""
    tasks_dir = Path(get_folder("tasks"))
    completed_dir = Path(get_folder("completed"))
    completed_dir.mkdir(parents=True, exist_ok=True)

    archived = []
    skipped = []

    for md_file in sorted(tasks_dir.glob("*.md")):
        if not has_frontmatter_field(md_file, "completed"):
            continue

        if has_frontmatter_field(md_file, "recurrence"):
            skipped.append(md_file.name)
            continue

        shutil.move(str(md_file), str(completed_dir / md_file.name))
        archived.append(md_file.name)

    # Report results
    if archived:
        print(f"Archived {len(archived)} completed task(s):\n")
        print("Moved to completed/:")
        for f in archived:
            print(f"  - {f}")

    if skipped:
        print(f"\nSkipped {len(skipped)} recurring task(s):")
        for f in skipped:
            print(f"  - {f} (has recurrence field, stays in tasks/)")

    if archived:
        print("\nTasks folder is now clean!")
    elif not skipped:
        print("No completed tasks to archive.")


def main():
    print("=== Archiving Completed Tasks ===\n")
    archive_completed_tasks()


if __name__ == "__main__":
    main()
