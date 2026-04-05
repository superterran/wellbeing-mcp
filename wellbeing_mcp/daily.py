"""
daily.py — markdown-first data layer.

Each day has one note: Well-being/Daily/YYYY-MM-DD.md
YAML frontmatter is the structured data store.
The body is regenerated from frontmatter on every write.
A '## Personal Notes' section at the bottom is preserved across regenerations.

Dataview queries in Obsidian can use the frontmatter directly:
  TABLE weight_lbs, mood, calories_total, workout_type
  FROM "Well-being/Daily"
  SORT date DESC
"""

from __future__ import annotations

import yaml
from pathlib import Path
from datetime import date, datetime, timedelta
from typing import Optional

VAULT_ROOT = Path.home() / "Documents" / "Cloud Vault"
DAILY_DIR = VAULT_ROOT / "Well-being" / "Daily"

# Sentinel used to preserve personal notes across regenerations
PERSONAL_NOTES_HEADER = "## Personal Notes"


# ---------------------------------------------------------------------------
# Frontmatter parsing
# ---------------------------------------------------------------------------

def _parse(text: str) -> tuple[dict, str]:
    """Split a note into (frontmatter_dict, personal_notes_text)."""
    fm: dict = {}
    personal_notes = ""

    if text.startswith("---\n"):
        parts = text.split("---\n", 2)
        if len(parts) >= 3:
            fm = yaml.safe_load(parts[1]) or {}
            body = parts[2]
        else:
            body = text
    else:
        body = text

    # Preserve anything under the personal notes header
    if PERSONAL_NOTES_HEADER in body:
        idx = body.index(PERSONAL_NOTES_HEADER)
        personal_notes = body[idx:]

    return fm, personal_notes


def _render(fm: dict, personal_notes: str = "") -> str:
    """Render a complete daily note from frontmatter."""
    d = date.fromisoformat(str(fm.get("date", date.today().isoformat())))
    day_str = d.strftime("%A, %B %-d %Y")

    # Weight section
    weight_lbs = fm.get("weight_lbs")
    goal = fm.get("goal_weight_lbs", 250)
    if weight_lbs:
        to_go = round(float(weight_lbs) - float(goal), 1)
        weight_body = f"{weight_lbs} lbs | goal: {goal} | {to_go} lbs to go"
    else:
        weight_body = "_not logged_"

    # Mood section
    mood = fm.get("mood")
    energy = fm.get("energy")
    mood_note = fm.get("mood_note", "")
    mood_parts = []
    if mood:
        mood_parts.append(f"{mood}/10 mood")
    if energy:
        mood_parts.append(f"{energy}/10 energy")
    if mood_note:
        mood_parts.append(f'"{mood_note}"')
    mood_body = " | ".join(mood_parts) if mood_parts else "_not logged_"

    # Meals section
    meals: list[dict] = fm.get("meals", []) or []
    calorie_target = fm.get("calorie_target", 2100)
    calories_total = fm.get("calories_total", 0) or 0
    if meals:
        meal_lines = []
        for m in meals:
            t = m.get("time", "")
            desc = m.get("description", "")
            cal = m.get("calories", "")
            prot = m.get("protein_g")
            prot_str = f" | {prot}g protein" if prot else ""
            meal_lines.append(f"- {t} — {desc} (~{cal} cal{prot_str})")
        remaining = calorie_target - calories_total
        remaining_str = f"{remaining} remaining" if remaining >= 0 else f"{abs(remaining)} over"
        meals_body = "\n".join(meal_lines) + f"\n\n**{calories_total} / {calorie_target} cal | {remaining_str}**"
    else:
        meals_body = f"_nothing logged_ | target: {calorie_target} cal"

    # Workout section
    workout_type = fm.get("workout_type", "")
    workout_minutes = fm.get("workout_minutes")
    if workout_type:
        w_parts = [workout_type]
        if workout_minutes:
            w_parts.append(f"{workout_minutes} min")
        log_path = f"Well-being/Workouts/Log/{d.isoformat()}"
        workout_body = " | ".join(w_parts) + f"\n[[{log_path}|View workout log]]"
    else:
        workout_body = "_not logged_"

    # Apple Health section
    ah_parts = []
    if fm.get("resting_heart_rate"):
        ah_parts.append(f"RHR {fm['resting_heart_rate']} bpm")
    if fm.get("hrv"):
        ah_parts.append(f"HRV {fm['hrv']} ms")
    if fm.get("steps"):
        ah_parts.append(f"{fm['steps']:,} steps")
    if fm.get("active_calories"):
        ah_parts.append(f"{fm['active_calories']} active cal")
    if fm.get("vo2_max"):
        ah_parts.append(f"VO₂max {fm['vo2_max']}")
    if fm.get("blood_oxygen"):
        ah_parts.append(f"SpO₂ {fm['blood_oxygen']}%")
    if fm.get("cardio_recovery"):
        ah_parts.append(f"cardio recovery {fm['cardio_recovery']}")
    apple_health_body = " | ".join(ah_parts) if ah_parts else "_no data_"

    fm_text = yaml.dump(fm, default_flow_style=False, allow_unicode=True, sort_keys=False)

    body = f"""# Well-being — {day_str}

## Weight

{weight_body}

## Mood

{mood_body}

## Meals

{meals_body}

## Workout

{workout_body}

## Apple Health

{apple_health_body}

"""

    if personal_notes:
        body += personal_notes + "\n"

    return f"---\n{fm_text}---\n{body}"


# ---------------------------------------------------------------------------
# Read / write
# ---------------------------------------------------------------------------

def _daily_path(d: date) -> Path:
    return DAILY_DIR / f"{d.isoformat()}.md"


def read_daily(d: Optional[date] = None) -> tuple[dict, str]:
    """Return (frontmatter, personal_notes) for the given day. Empty dict if no note."""
    d = d or date.today()
    path = _daily_path(d)
    if not path.exists():
        return {}, ""
    return _parse(path.read_text())


def _default_fm(d: date) -> dict:
    return {
        "type": "daily-log",
        "date": d.isoformat(),
        "weight_lbs": None,
        "goal_weight_lbs": 250,
        "mood": None,
        "energy": None,
        "mood_note": "",
        "calories_total": 0,
        "calorie_target": 2100,
        "workout_type": "",
        "workout_minutes": None,
        "meals": [],
        # Apple Health metrics
        "resting_heart_rate": None,
        "hrv": None,
        "steps": None,
        "active_calories": None,
        "vo2_max": None,
        "blood_oxygen": None,
        "cardio_recovery": None,
        "tags": ["well-being", "daily"],
    }


def _save(d: date, fm: dict, personal_notes: str = "") -> None:
    DAILY_DIR.mkdir(parents=True, exist_ok=True)
    _daily_path(d).write_text(_render(fm, personal_notes))


def _load_or_create(d: date) -> tuple[dict, str]:
    fm, notes = read_daily(d)
    if not fm:
        fm = _default_fm(d)
    return fm, notes


# ---------------------------------------------------------------------------
# Logging helpers
# ---------------------------------------------------------------------------

def log_weight(weight_lbs: float, d: Optional[date] = None) -> str:
    d = d or date.today()
    fm, notes = _load_or_create(d)
    fm["weight_lbs"] = weight_lbs
    _save(d, fm, notes)
    goal = fm.get("goal_weight_lbs", 250)
    to_go = round(weight_lbs - goal, 1)
    return f"Logged {weight_lbs} lbs on {d}. {to_go} lbs to goal ({goal})."


def log_mood(score: Optional[int], energy: Optional[int], note: str = "", d: Optional[date] = None) -> str:
    d = d or date.today()
    fm, notes = _load_or_create(d)
    if score is not None:
        fm["mood"] = score
    if energy is not None:
        fm["energy"] = energy
    if note:
        fm["mood_note"] = note
    _save(d, fm, notes)
    parts = []
    if score is not None:
        parts.append(f"mood {score}/10")
    if energy is not None:
        parts.append(f"energy {energy}/10")
    if note:
        parts.append(f'"{note}"')
    return f"Logged: {', '.join(parts)}"


def log_meal(
    description: str,
    calories: int,
    protein_g: Optional[int] = None,
    meal_time: Optional[str] = None,
    d: Optional[date] = None,
) -> str:
    d = d or date.today()
    fm, notes = _load_or_create(d)

    t = meal_time or datetime.now().strftime("%H:%M")
    entry: dict = {"time": t, "description": description, "calories": calories}
    if protein_g:
        entry["protein_g"] = protein_g

    meals = fm.get("meals") or []
    meals.append(entry)
    fm["meals"] = meals
    fm["calories_total"] = sum(m.get("calories", 0) for m in meals)

    _save(d, fm, notes)

    target = fm.get("calorie_target", 2100)
    total = fm["calories_total"]
    remaining = target - total
    return (
        f"Logged: {description} (~{calories} cal)\n"
        f"Today: {total} / {target} cal | {remaining} remaining"
    )


def log_workout_to_daily(
    workout_type: str,
    duration_minutes: Optional[int] = None,
    d: Optional[date] = None,
) -> None:
    """Update the daily note's workout fields (called when finishing a gym session)."""
    d = d or date.today()
    fm, notes = _load_or_create(d)
    fm["workout_type"] = workout_type
    if duration_minutes is not None:
        fm["workout_minutes"] = duration_minutes
    _save(d, fm, notes)


def log_apple_health_metrics(
    d: Optional[date] = None,
    resting_heart_rate: Optional[float] = None,
    hrv: Optional[float] = None,
    steps: Optional[int] = None,
    active_calories: Optional[int] = None,
    vo2_max: Optional[float] = None,
    blood_oxygen: Optional[float] = None,
    cardio_recovery: Optional[float] = None,
) -> None:
    """Write Apple Health metrics to the daily note for the given date."""
    d = d or date.today()
    fm, notes = _load_or_create(d)
    if resting_heart_rate is not None:
        fm["resting_heart_rate"] = round(resting_heart_rate, 1)
    if hrv is not None:
        fm["hrv"] = round(hrv, 1)
    if steps is not None:
        fm["steps"] = int(steps)
    if active_calories is not None:
        fm["active_calories"] = int(active_calories)
    if vo2_max is not None:
        fm["vo2_max"] = round(vo2_max, 1)
    if blood_oxygen is not None:
        fm["blood_oxygen"] = round(blood_oxygen, 1)
    if cardio_recovery is not None:
        fm["cardio_recovery"] = round(cardio_recovery, 1)
    _save(d, fm, notes)


# ---------------------------------------------------------------------------
# Query helpers
# ---------------------------------------------------------------------------

def get_calories_today() -> int:
    fm, _ = read_daily(date.today())
    return fm.get("calories_total", 0) or 0


def get_latest_mood() -> Optional[dict]:
    """Scan back up to 7 days for the most recent mood entry."""
    for i in range(7):
        d = date.today() - timedelta(days=i)
        fm, _ = read_daily(d)
        if fm.get("mood") or fm.get("energy"):
            return {
                "date": str(fm.get("date", d)),
                "score": fm.get("mood"),
                "energy": fm.get("energy"),
                "note": fm.get("mood_note", ""),
            }
    return None


def get_latest_weight() -> Optional[dict]:
    """Scan back up to 30 days for the most recent weight entry."""
    for i in range(30):
        d = date.today() - timedelta(days=i)
        fm, _ = read_daily(d)
        if fm.get("weight_lbs"):
            return {"date": str(fm.get("date", d)), "weight_lbs": fm["weight_lbs"]}
    return None


def get_weight_trend(days: int = 14) -> list[dict]:
    """Return weight entries for the past N days (only days with a logged weight)."""
    entries = []
    for i in range(days - 1, -1, -1):
        d = date.today() - timedelta(days=i)
        fm, _ = read_daily(d)
        if fm.get("weight_lbs"):
            entries.append({"date": str(fm.get("date", d)), "weight_lbs": fm["weight_lbs"]})
    return entries


def get_last_workout_info() -> Optional[dict]:
    """Scan back up to 30 days for the most recent logged workout."""
    for i in range(30):
        d = date.today() - timedelta(days=i)
        fm, _ = read_daily(d)
        if fm.get("workout_type"):
            return {
                "date": str(fm.get("date", d)),
                "workout_type": fm["workout_type"],
                "workout_minutes": fm.get("workout_minutes"),
                "days_ago": i,
            }
    return None


def get_workouts_this_week() -> list[dict]:
    """Return workout entries for the current week (Mon–today)."""
    today = date.today()
    monday = today - timedelta(days=today.weekday())
    entries = []
    for i in range((today - monday).days + 1):
        d = monday + timedelta(days=i)
        fm, _ = read_daily(d)
        if fm.get("workout_type"):
            entries.append({
                "date": str(d),
                "workout_type": fm["workout_type"],
                "workout_minutes": fm.get("workout_minutes"),
            })
    return entries


# ---------------------------------------------------------------------------
# Snapshot (used by wellbeing://current resource)
# ---------------------------------------------------------------------------

def build_current_snapshot(profile: dict) -> str:
    today = date.today().isoformat()

    # Weight
    latest_weight = get_latest_weight()
    weight_trend = get_weight_trend(days=14)
    goal = profile.get("goal_weight_lbs", 250)
    if latest_weight:
        lw = latest_weight["weight_lbs"]
        logged_date = latest_weight["date"]
        age_note = "" if logged_date == today else f" (logged {logged_date})"
        to_go = round(lw - goal, 1)
        weight_line = f"{lw} lbs{age_note} | {to_go} to goal ({goal})"
        if len(weight_trend) >= 2:
            delta = round(weight_trend[-1]["weight_lbs"] - weight_trend[0]["weight_lbs"], 1)
            arrow = "↓" if delta < 0 else "↑" if delta > 0 else "→"
            weight_line += f" | 2-week: {arrow}{abs(delta)} lbs"
    else:
        weight_line = f"not logged (est. ~{profile.get('current_weight_estimate_lbs', '?')} lbs | goal: {goal})"

    # Workout
    last_w = get_last_workout_info()
    week_workouts = get_workouts_this_week()
    if last_w:
        ago = "today" if last_w["days_ago"] == 0 else f"{last_w['days_ago']}d ago"
        workout_line = f"{len(week_workouts)} this week | last: {last_w['workout_type']} ({ago})"
    else:
        workout_line = "none logged yet"

    # Calories
    cal_today = get_calories_today()
    target = profile.get("calorie_target", 2100)
    if cal_today:
        remaining = target - cal_today
        cal_line = f"{cal_today} / {target} cal | {remaining} remaining"
    else:
        cal_line = f"0 / {target} — nothing logged today"

    # Mood
    mood = get_latest_mood()
    if mood:
        parts = []
        if mood["score"]:
            parts.append(f"mood {mood['score']}/10")
        if mood["energy"]:
            parts.append(f"energy {mood['energy']}/10")
        if mood["note"]:
            parts.append(f'"{mood["note"]}"')
        age = f" ({mood['date']})" if mood["date"] != today else ""
        mood_line = ", ".join(parts) + age
    else:
        mood_line = "not logged"

    # Apple Health — pull from today's note
    fm_today, _ = read_daily(date.today())
    ah_parts = []
    if fm_today.get("resting_heart_rate"):
        ah_parts.append(f"RHR {fm_today['resting_heart_rate']} bpm")
    if fm_today.get("hrv"):
        ah_parts.append(f"HRV {fm_today['hrv']} ms")
    if fm_today.get("steps"):
        ah_parts.append(f"{fm_today['steps']:,} steps")
    if fm_today.get("active_calories"):
        ah_parts.append(f"{fm_today['active_calories']} active cal")
    if fm_today.get("vo2_max"):
        ah_parts.append(f"VO₂max {fm_today['vo2_max']}")
    ah_line = " | ".join(ah_parts) if ah_parts else "no data today"

    return f"""[Wellbeing — {today}]
Weight:    {weight_line}
Workouts:  {workout_line}
Calories:  {cal_line}
Mood:      {mood_line}
Health:    {ah_line}
Injury:    Right shoulder tendon — mostly healed, avoid heavy pressing
Context:   Returning after ~4 weeks off (injury + illness). Elliptical is priority.
Goal:      {goal} lbs | {target} cal/day target"""
