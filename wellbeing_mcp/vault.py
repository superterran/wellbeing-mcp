"""
vault.py — writes well-being journal entries and workout logs directly
to the Obsidian vault filesystem.

Vault root: ~/Documents/Cloud Vault/
Well-being directory: ~/Documents/Cloud Vault/Well-being/

The vault watcher (obsidian-vault-watcher.service) picks up changes and
auto-commits/pushes. Obsidian Sync propagates to all devices.
"""

import re
from datetime import date
from pathlib import Path

VAULT_ROOT = Path.home() / "Documents" / "Cloud Vault"
WELLBEING_DIR = VAULT_ROOT / "Well-being"

JOURNAL_WEEKLY = WELLBEING_DIR / "Journal" / "Weekly"
JOURNAL_MONTHLY = WELLBEING_DIR / "Journal" / "Monthly"
WORKOUT_LOG_DIR = WELLBEING_DIR / "Workouts" / "Log"
ROUTINES_DIR = WELLBEING_DIR / "Workouts" / "Routines"
CURRENT_ROUTINE_PATH = ROUTINES_DIR / "Current Routine.md"


def _ensure_dirs() -> None:
    for d in (JOURNAL_WEEKLY, JOURNAL_MONTHLY, WORKOUT_LOG_DIR, ROUTINES_DIR):
        d.mkdir(parents=True, exist_ok=True)


def _iso_week(d: date) -> str:
    """Return ISO week string like '2026-W14'."""
    return f"{d.year}-W{d.isocalendar()[1]:02d}"


# ---------------------------------------------------------------------------
# Routine
# ---------------------------------------------------------------------------

def read_routine() -> str:
    """Read the current workout routine from the vault."""
    if CURRENT_ROUTINE_PATH.exists():
        return CURRENT_ROUTINE_PATH.read_text()
    return "(No routine saved yet.)"


def write_routine(content: str) -> str:
    """Write/replace the current workout routine in the vault."""
    _ensure_dirs()
    CURRENT_ROUTINE_PATH.write_text(content)
    return str(CURRENT_ROUTINE_PATH.relative_to(VAULT_ROOT))


# ---------------------------------------------------------------------------
# Workout session log
# ---------------------------------------------------------------------------

def write_workout_log(
    session_type: str,
    exercises: list[dict],
    total_minutes: int | None = None,
    notes: str = "",
    session_date: date | None = None,
) -> str:
    """
    Write a completed workout session to the vault.
    Returns the vault-relative path of the note.
    """
    _ensure_dirs()
    d = session_date or date.today()
    filename = f"{d.isoformat()}.md"
    path = WORKOUT_LOG_DIR / filename

    # Build exercise table
    if exercises:
        ex_lines = ["| Exercise | Sets | Reps | Weight | RPE | Notes |",
                    "|----------|------|------|--------|-----|-------|"]
        last_name = None
        for ex in exercises:
            name = ex.get("name", "")
            display_name = name if name != last_name else ""
            last_name = name
            modified = " ⚠️" if ex.get("modified") else ""
            ex_lines.append(
                f"| {display_name}{modified} "
                f"| {ex.get('set_number', '')} "
                f"| {ex.get('reps', '')} "
                f"| {ex.get('weight_lbs', '') or '—'} lbs "
                f"| {ex.get('rpe', '') or '—'} "
                f"| {ex.get('note', '') or ''} |"
            )
        ex_table = "\n".join(ex_lines)
    else:
        ex_table = "_No exercises logged._"

    duration_str = f"{total_minutes} min" if total_minutes else "—"
    week = _iso_week(d)

    content = f"""---
type: workout-log
date: {d.isoformat()}
week: {week}
session_type: {session_type}
duration_minutes: {total_minutes or ""}
tags: [well-being, workout, {session_type}]
---

# Workout — {d.strftime("%A, %B %-d %Y")}

**Type:** {session_type}
**Duration:** {duration_str}

## Exercises

{ex_table}

## Notes

{notes or "_No notes._"}
"""

    # Append to existing note if same day (multiple sessions)
    if path.exists():
        existing = path.read_text()
        path.write_text(existing + "\n---\n\n" + content)
    else:
        path.write_text(content)

    return str(path.relative_to(VAULT_ROOT))


# ---------------------------------------------------------------------------
# Weekly journal
# ---------------------------------------------------------------------------

def write_weekly_review(
    week_label: str | None = None,
    weight_entries: list[dict] | None = None,
    workout_count: int = 0,
    avg_calories: int | None = None,
    mood_avg: float | None = None,
    highlights: str = "",
    challenges: str = "",
    next_week_focus: str = "",
) -> str:
    """
    Write or update the weekly well-being journal note.
    Returns vault-relative path.
    """
    _ensure_dirs()
    today = date.today()
    week = week_label or _iso_week(today)
    filename = f"{week}.md"
    path = JOURNAL_WEEKLY / filename

    # Weight section
    if weight_entries:
        weights = [e["weight_lbs"] for e in weight_entries]
        w_min, w_max, w_avg = min(weights), max(weights), round(sum(weights) / len(weights), 1)
        w_last = weight_entries[-1]["weight_lbs"]
        w_first = weight_entries[0]["weight_lbs"]
        delta = round(w_last - w_first, 1)
        direction = "↓" if delta < 0 else "↑" if delta > 0 else "→"
        weight_section = f"- **Range:** {w_min}–{w_max} lbs\n- **Avg:** {w_avg} lbs\n- **Trend:** {direction} {abs(delta)} lbs over the week"
    else:
        weight_section = "_No weight logged this week._"

    mood_str = f"{mood_avg:.1f}/10" if mood_avg else "_not tracked_"
    cal_str = f"~{avg_calories} cal/day avg" if avg_calories else "_not tracked_"

    # Parse year/week from label
    match = re.match(r"(\d{4})-W(\d{2})", week)
    year_str = match.group(1) if match else str(today.year)

    content = f"""---
type: weekly-review
week: {week}
year: {year_str}
tags: [well-being, weekly-review, journal]
---

# Well-being — Week {week}

## At a Glance

| Metric | This Week |
|--------|-----------|
| Workouts | {workout_count} |
| Avg mood | {mood_str} |
| Avg calories | {cal_str} |

## Weight

{weight_section}

## Highlights

{highlights or "_Nothing noted._"}

## Challenges

{challenges or "_Nothing noted._"}

## Next Week Focus

{next_week_focus or "_TBD._"}
"""

    path.write_text(content)
    return str(path.relative_to(VAULT_ROOT))


# ---------------------------------------------------------------------------
# Monthly journal
# ---------------------------------------------------------------------------

def write_monthly_review(
    year: int,
    month: int,
    weight_start: float | None = None,
    weight_end: float | None = None,
    total_workouts: int = 0,
    summary: str = "",
    wins: str = "",
    focus_next_month: str = "",
) -> str:
    """
    Write or update the monthly well-being journal note.
    Returns vault-relative path.
    """
    _ensure_dirs()
    month_label = f"{year}-{month:02d}"
    month_name = date(year, month, 1).strftime("%B %Y")
    filename = f"{month_label}.md"
    path = JOURNAL_MONTHLY / filename

    weight_delta = ""
    if weight_start and weight_end:
        delta = round(weight_end - weight_start, 1)
        direction = "↓" if delta < 0 else "↑" if delta > 0 else "→"
        weight_delta = f"{direction} {abs(delta)} lbs ({weight_start} → {weight_end})"
    elif weight_end:
        weight_delta = f"{weight_end} lbs at month end"

    content = f"""---
type: monthly-review
month: {month_label}
tags: [well-being, monthly-review, journal]
---

# Well-being — {month_name}

## Summary

{summary or "_No summary yet._"}

## Stats

| Metric | Value |
|--------|-------|
| Total workouts | {total_workouts} |
| Weight change | {weight_delta or "_not tracked_"} |

## Wins

{wins or "_Nothing noted._"}

## Focus for Next Month

{focus_next_month or "_TBD._"}
"""

    path.write_text(content)
    return str(path.relative_to(VAULT_ROOT))
