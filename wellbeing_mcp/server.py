"""
wellbeing-mcp — FastMCP server.

Exposes tools for logging mood, weight, meals, and workouts,
plus a wellbeing://current resource that surfaces today's state
as background context in every Claude conversation.

All persistent data lives in markdown daily notes (daily.py).
SQLite is used only for active gym session state (db.py).
"""


from fastmcp import FastMCP

from . import daily, db, vault
from . import workout as wk

mcp = FastMCP(
    "wellbeing",
    instructions=(
        "Wellbeing and coaching server for Doug. "
        "Always read wellbeing://current at session start for today's snapshot. "
        "For gym sessions, read wellbeing://gym-session and use the 'coach' prompt. "
        "Log exercises conversationally as they're reported — don't make the user fill out forms."
    ),
)

db.init_db()


# ---------------------------------------------------------------------------
# Resources: auto-loaded context
# ---------------------------------------------------------------------------

@mcp.resource("wellbeing://current")
def current_state() -> str:
    """Today's wellbeing snapshot — weight, workouts, calories, mood."""
    profile = db.get_profile()
    return daily.build_current_snapshot(profile)


@mcp.resource("wellbeing://profile")
def user_profile() -> str:
    """User background: history, goals, injury status, coaching notes."""
    profile = db.get_profile()
    lines = [
        f"Name: {profile.get('name', 'Doug')}",
        f"Age: {profile.get('age', 41)}",
        f"History: {profile.get('history', '')}",
        f"Goal: {profile.get('goal_weight_lbs', 250)} lbs",
        f"Calorie target: {profile.get('calorie_target', 2100)}/day",
        f"Injury: {profile.get('injury', '')}",
        f"Illness recovery: {profile.get('illness_recovery', '')}",
        f"Preferred cardio: {profile.get('preferred_cardio', 'elliptical')}",
        f"Diet challenge: {profile.get('main_diet_challenge', 'snacking')}",
        f"Diet baseline: {profile.get('diet_baseline', '')}",
        f"Scale note: {profile.get('scale_note', '')}",
        f"Partner: {profile.get('partner', 'Kaylin')}",
        f"Coaching tone: {profile.get('coaching_tone', '')}",
    ]
    return "\n".join(lines)


@mcp.resource("wellbeing://gym-session")
def gym_session_state() -> str:
    """Live gym session state — active session, exercises logged, what's next."""
    session = db.get_active_session()
    if not session:
        last = db.get_last_gym_session()
        if last:
            days = wk.get_days_since_last_session()
            ago = "today" if days == 0 else f"{days}d ago"
            return f"No active session. Last: {last.get('session_type', '?')} ({ago})"
        return "No active session. No previous sessions on record."

    session_id = session["id"]
    session_type = session.get("session_type", "unknown")
    profile = db.get_profile()
    shoulder_ok = "healed" in profile.get("injury", "").lower() or "fine" in profile.get("injury", "").lower()
    return wk.format_session_status(session_id, session_type, shoulder_ok=shoulder_ok)


# ---------------------------------------------------------------------------
# Prompts: coaching persona
# ---------------------------------------------------------------------------

@mcp.prompt()
def coach() -> str:
    """
    Activate the gym coaching persona. Use this at the start of any gym or
    workout conversation to establish tone, context, and session flow.
    """
    profile = db.get_profile()
    snapshot = daily.build_current_snapshot(profile)
    session = db.get_active_session()

    session_block = ""
    if session:
        session_type = session.get("session_type", "unknown")
        exercises = db.get_session_exercises(session["id"])
        session_block = (
            f"\n\nACTIVE SESSION: {session_type} (id={session['id']}), "
            f"{len(exercises)} exercises logged so far."
        )
    else:
        session_type, rationale = wk.determine_session_type()
        days_since = wk.get_days_since_last_session()
        session_block = (
            f"\n\nNO ACTIVE SESSION. Recommended today: {session_type}. "
            f"Rationale: {rationale} "
            f"Days since last session: {days_since}."
        )

    return f"""You are Doug's personal trainer and coach. Here's everything you need:

## Current State
{snapshot}
{session_block}

## Your Role
- Run gym sessions conversationally. Walk him through exercises one at a time.
- When he says he's done with something, log it immediately using log_exercise_set — don't ask him to do it.
- Call start_gym_session at the start if there's no active session.
- Call get_next_exercise after each logged exercise to know what's up next.
- During cardio (elliptical, stair machine), keep conversation going. Talk about anything — topics, news, strategy, whatever keeps him moving. Check in on effort every ~10 min.
- If equipment is unavailable, use suggest_exercise_substitute or set_unavailable_equipment to adjust the plan. Don't just say "that's not available."
- At the end, call finish_gym_session to write the vault log.

## Tone
{profile.get('coaching_tone', 'Direct and practical. No cheerleading.')}

## Injury Awareness
{profile.get('injury', 'Right shoulder — check before any pressing movement.')}
Current status: mostly healed, avoid heavy pressing. All pulling and lower body is fine.

## Rules
- Never repeat the plan back in full. Just tell him the next exercise.
- If he's on cardio, engage him — silence is fine but conversation is better.
- Log first, talk after. Don't make him wait while you format things.
- Notice effort and RPE from how he describes sets. Log rpe if he says "easy", "hard", "felt heavy", etc.
- When in doubt, ask one short question, not three.
"""


# ---------------------------------------------------------------------------
# Tools: daily logging
# ---------------------------------------------------------------------------

@mcp.tool()
def log_mood(
    score: int | None = None,
    energy: int | None = None,
    note: str = "",
) -> str:
    """
    Log current mood and/or energy level to today's daily note.

    Args:
        score:  Mood score 1–10 (1 = terrible, 10 = great). Optional.
        energy: Energy level 1–10. Optional.
        note:   Short description, e.g. "a bit frustrated" or "solid". Optional.
    """
    if score is None and energy is None and not note:
        return "Nothing logged — provide at least a score, energy, or note."
    return daily.log_mood(score, energy, note)


@mcp.tool()
def log_weight(weight_lbs: float) -> str:
    """
    Log a weight measurement in pounds to today's daily note.

    Args:
        weight_lbs: Weight in lbs.
    """
    return daily.log_weight(weight_lbs)


@mcp.tool()
def log_meal(
    description: str,
    estimated_calories: int | None = None,
    estimated_protein_g: int | None = None,
) -> str:
    """
    Log a meal or snack to today's daily note. Describe it naturally.
    If calories are not provided, they will be estimated from the description.

    Args:
        description:         What you ate, e.g. "grilled chicken breast, rice, salad".
        estimated_calories:  Calorie estimate. If omitted, estimated from description.
        estimated_protein_g: Protein estimate in grams. Optional.
    """
    if estimated_calories is None:
        estimated_calories = _estimate_calories(description)
    return daily.log_meal(description, estimated_calories, estimated_protein_g)


# ---------------------------------------------------------------------------
# Tools: gym session (interactive)
# ---------------------------------------------------------------------------

@mcp.tool()
def get_workout_plan(shoulder_ok: bool = True) -> str:
    """
    Get today's recommended workout plan with exercises.
    Returns a formatted plan ready for gym-floor use.

    Args:
        shoulder_ok: Set False if right shoulder is bothering you today.
    """
    session_type, rationale = wk.determine_session_type()
    plan = wk.build_workout_plan(session_type, shoulder_ok=shoulder_ok)
    days_since = wk.get_days_since_last_session()
    return wk.format_plan_for_conversation(plan, rationale, days_since)


@mcp.tool()
def start_gym_session(session_type: str = "") -> str:
    """
    Start a new gym session. Returns the session ID to use when logging exercises.

    Args:
        session_type: Optional override — "A-push", "B-pull-lower", or "cardio".
                      If omitted, the recommended type is used automatically.
    """
    if not session_type:
        session_type, _ = wk.determine_session_type()
    session_id = db.start_gym_session(session_type)
    return f"Session started (id={session_id}, type={session_type}). Log each exercise as you go."


@mcp.tool()
def log_exercise_set(
    name: str,
    set_number: int | None = None,
    reps: int | None = None,
    weight_lbs: float | None = None,
    rpe: int | None = None,
    modified: bool = False,
    note: str = "",
) -> str:
    """
    Log one set of an exercise during an active gym session.

    Args:
        name:       Exercise name, e.g. "Leg Press" or "Elliptical".
        set_number: Which set this is (1, 2, 3...). Optional.
        reps:       Reps completed. Optional (omit for timed exercises).
        weight_lbs: Weight used in lbs. Optional.
        rpe:        Rate of perceived exertion 1–10. Optional.
        modified:   True if substituted/modified from the plan. Default False.
        note:       Any short note, e.g. "felt easy", "stopped early". Optional.
    """
    session = db.get_active_session()
    if not session:
        return "No active session. Call start_gym_session first."
    db.log_exercise(
        session["id"], name, set_number, reps, weight_lbs, rpe, modified, note
    )
    parts = [name]
    if set_number:
        parts.append(f"set {set_number}")
    if reps:
        parts.append(f"{reps} reps")
    if weight_lbs:
        parts.append(f"@ {weight_lbs} lbs")
    if rpe:
        parts.append(f"RPE {rpe}")
    return f"Logged: {' | '.join(parts)}"


@mcp.tool()
def finish_gym_session(notes: str = "") -> str:
    """
    Finish the active gym session, write a workout log to the vault,
    and update today's daily note with the workout.

    Args:
        notes: Optional session notes, e.g. "shoulder felt fine", "cut short".
    """
    session = db.get_active_session()
    if not session:
        return "No active session found."

    session_id = session["id"]
    session_type = session.get("session_type", "unknown")

    # Close out the session in SQLite
    result = db.finish_gym_session(session_id, notes=notes)
    total_minutes = result.get("total_minutes")

    # Get exercises and write vault log
    exercises = db.get_session_exercises(session_id)
    vault_path = vault.write_workout_log(
        session_type=session_type,
        exercises=exercises,
        total_minutes=total_minutes,
        notes=notes,
    )

    # Update today's daily note
    daily.log_workout_to_daily(session_type, total_minutes)

    summary = wk.summarize_session(session_id)
    return f"{summary}\nVault: {vault_path}"


@mcp.tool()
def get_active_session_status() -> str:
    """Check if there's an active gym session and what's been logged so far."""
    session = db.get_active_session()
    if not session:
        return "No active session."

    exercises = db.get_session_exercises(session["id"])
    lines = [
        f"Active session: {session.get('session_type', 'unknown')} (id={session['id']})",
        f"Started: {session.get('started_at', '?')}",
        f"Exercises logged: {len(exercises)}",
    ]
    if exercises:
        for ex in exercises[-5:]:  # last 5 entries
            parts = [ex["name"]]
            if ex.get("set_number"):
                parts.append(f"set {ex['set_number']}")
            if ex.get("reps"):
                parts.append(f"{ex['reps']} reps")
            if ex.get("weight_lbs"):
                parts.append(f"@ {ex['weight_lbs']} lbs")
            lines.append("  " + " | ".join(parts))
    return "\n".join(lines)


@mcp.tool()
def get_next_exercise() -> str:
    """
    Return the next unlogged exercise in the current session's plan.
    Call this after logging each exercise to know what's up next.
    """
    session = db.get_active_session()
    if not session:
        return "No active session."
    profile = db.get_profile()
    shoulder_ok = "healed" in profile.get("injury", "").lower()
    return wk.get_next_exercise(session["id"], session.get("session_type", "cardio"), shoulder_ok)


@mcp.tool()
def suggest_exercise_substitute(exercise_name: str) -> str:
    """
    Suggest substitutes for an exercise — use when equipment is unavailable or
    Doug wants to swap something out.

    Args:
        exercise_name: The exercise to find a substitute for, e.g. "Leg Press".
    """
    return wk.suggest_substitute(exercise_name)


@mcp.tool()
def set_unavailable_equipment(unavailable: list[str], shoulder_ok: bool = True) -> str:
    """
    Rebuild today's workout plan around unavailable equipment and return
    the updated plan. Call this when Doug reports what's taken or broken.

    Args:
        unavailable: List of equipment names that are unavailable,
                     e.g. ["cable machine", "stair machine"].
        shoulder_ok: Whether the shoulder is feeling fine today. Default True.
    """
    session = db.get_active_session()
    if not session:
        # No active session — just return a modified plan preview
        session_type, rationale = wk.determine_session_type()
    else:
        session_type = session.get("session_type", "cardio")
        rationale = ""

    template = wk.ROUTINE.get(session_type, wk.ROUTINE["cardio"])
    exercises = wk._apply_shoulder_mods(template["exercises"], shoulder_ok)
    exercises = wk.apply_equipment_mods(exercises, unavailable)

    plan = {
        "session_type": session_type,
        "label": template["label"],
        "exercises": exercises,
        "shoulder_modified": not shoulder_ok,
    }
    unavail_str = ", ".join(unavailable) if unavailable else "none"
    result = f"Plan updated — unavailable: {unavail_str}\n\n"
    result += wk.format_plan_for_conversation(plan, rationale)
    return result


# ---------------------------------------------------------------------------
# Tools: vault / journal
# ---------------------------------------------------------------------------

@mcp.tool()
def get_routine() -> str:
    """Read the current workout routine from the vault."""
    return vault.read_routine()


@mcp.tool()
def update_routine(content: str) -> str:
    """
    Write or replace the current workout routine in the vault.

    Args:
        content: Full markdown content of the routine note.
    """
    path = vault.write_routine(content)
    return f"Routine updated: {path}"


@mcp.tool()
def write_weekly_review(
    highlights: str = "",
    challenges: str = "",
    next_week_focus: str = "",
) -> str:
    """
    Write this week's well-being journal entry to the vault.

    Args:
        highlights:      What went well this week.
        challenges:      What was hard or didn't go as planned.
        next_week_focus: One or two priorities for next week.
    """
    from datetime import date, timedelta

    weight_entries = daily.get_weight_trend(days=7)
    week_workouts = daily.get_workouts_this_week()

    # Average calories for the week
    cal_values = []
    today = date.today()
    for i in range(7):
        d = today - timedelta(days=i)
        fm, _ = daily.read_daily(d)
        cal = fm.get("calories_total", 0)
        if cal:
            cal_values.append(cal)
    avg_cal = int(sum(cal_values) / len(cal_values)) if cal_values else None

    # Average mood
    mood_values = []
    for i in range(7):
        d = today - timedelta(days=i)
        fm, _ = daily.read_daily(d)
        if fm.get("mood"):
            mood_values.append(fm["mood"])
    avg_mood = round(sum(mood_values) / len(mood_values), 1) if mood_values else None

    path = vault.write_weekly_review(
        weight_entries=weight_entries,
        workout_count=len(week_workouts),
        avg_calories=avg_cal,
        mood_avg=avg_mood,
        highlights=highlights,
        challenges=challenges,
        next_week_focus=next_week_focus,
    )
    return f"Weekly review written: {path}"


@mcp.tool()
def write_monthly_review(
    year: int,
    month: int,
    summary: str = "",
    wins: str = "",
    focus_next_month: str = "",
) -> str:
    """
    Write a monthly well-being review to the vault.

    Args:
        year:             Year, e.g. 2026.
        month:            Month number 1–12.
        summary:          Brief narrative of the month.
        wins:             Notable wins or achievements.
        focus_next_month: What to prioritize next month.
    """
    from calendar import monthrange
    from datetime import date, timedelta

    # First and last weight entries in the month
    _, last_day = monthrange(year, month)
    first_date = date(year, month, 1)
    last_date = date(year, month, last_day)

    weight_start = None
    weight_end = None
    for i in range((last_date - first_date).days + 1):
        d = first_date + timedelta(days=i)
        fm, _ = daily.read_daily(d)
        if fm.get("weight_lbs"):
            if weight_start is None:
                weight_start = fm["weight_lbs"]
            weight_end = fm["weight_lbs"]

    # Count workouts in month
    workout_count = 0
    for i in range((last_date - first_date).days + 1):
        d = first_date + timedelta(days=i)
        fm, _ = daily.read_daily(d)
        if fm.get("workout_type"):
            workout_count += 1

    path = vault.write_monthly_review(
        year=year,
        month=month,
        weight_start=weight_start,
        weight_end=weight_end,
        total_workouts=workout_count,
        summary=summary,
        wins=wins,
        focus_next_month=focus_next_month,
    )
    return f"Monthly review written: {path}"


# ---------------------------------------------------------------------------
# Tools: retrieval / summary
# ---------------------------------------------------------------------------

@mcp.tool()
def get_today_summary() -> str:
    """Get today's full wellbeing snapshot."""
    profile = db.get_profile()
    return daily.build_current_snapshot(profile)


@mcp.tool()
def get_weekly_summary() -> str:
    """Get a summary of the past 7 days: workouts, weight trend, average calories."""
    week_workouts = daily.get_workouts_this_week()
    weight_trend = daily.get_weight_trend(days=7)

    workout_lines = []
    for w in week_workouts:
        parts = [f"{w['date']}: {w['workout_type']}"]
        if w.get("workout_minutes"):
            parts.append(f"{w['workout_minutes']}min")
        workout_lines.append(" | ".join(parts))

    weight_lines = [f"{w['date']}: {w['weight_lbs']} lbs" for w in weight_trend]

    lines = ["=== Past 7 Days ===", ""]
    lines.append(f"Workouts ({len(week_workouts)}):")
    lines.extend(workout_lines if workout_lines else ["  none logged"])
    lines.append("")
    lines.append(f"Weight ({len(weight_trend)} entries):")
    lines.extend(weight_lines if weight_lines else ["  none logged"])

    if len(weight_trend) >= 2:
        delta = round(weight_trend[-1]["weight_lbs"] - weight_trend[0]["weight_lbs"], 1)
        direction = "down" if delta < 0 else "up"
        lines.append(f"\n7-day trend: {direction} {abs(delta)} lbs")

    return "\n".join(lines)


@mcp.tool()
def update_profile_field(field: str, value: str) -> str:
    """
    Update a single field in the user profile (stored in ~/.local/share/wellbeing-mcp/profile.json).

    Args:
        field: Profile key, e.g. "goal_weight_lbs", "calorie_target", "injury".
        value: New value as a string (numbers will be converted automatically).
    """
    profile = db.get_profile()
    numeric_fields = {"goal_weight_lbs", "calorie_target", "age", "current_weight_estimate_lbs"}
    if field in numeric_fields:
        try:
            value = float(value) if "." in value else int(value)
        except ValueError:
            return f"Couldn't parse '{value}' as a number for field '{field}'."
    profile[field] = value
    db.save_profile(profile)
    return f"Updated profile: {field} = {value}"


# ---------------------------------------------------------------------------
# Internal: calorie estimation
# ---------------------------------------------------------------------------

def _estimate_calories(description: str) -> int:
    """
    Rough calorie estimation from natural language description.
    Good enough for trend tracking — not a substitute for precise logging.
    """
    desc = description.lower()

    estimates = {
        # Proteins
        "chicken breast": 165, "grilled chicken": 200, "salmon": 230,
        "steak": 300, "ground beef": 250, "turkey": 180, "eggs": 70,
        "protein shake": 150, "greek yogurt": 100, "cottage cheese": 110,
        # Carbs
        "rice": 200, "pasta": 220, "bread": 80, "sandwich": 350,
        "oatmeal": 150, "banana": 90, "apple": 80, "potato": 160,
        # Common meals
        "salad": 120, "caesar salad": 200, "burrito": 500, "burger": 550,
        "pizza slice": 280, "pizza": 700, "wrap": 350,
        "soup": 150, "chili": 250,
        # Drinks / snacks
        "coffee": 5, "latte": 120, "soda": 140, "juice": 110,
        "protein bar": 200, "granola bar": 190, "chips": 150,
        "cookie": 80, "handful of nuts": 170, "nuts": 170,
        # Fast food
        "mcdonald's": 700, "subway": 450, "chipotle": 800,
    }

    total = 0
    matched = False
    for keyword, cal in estimates.items():
        if keyword in desc:
            total += cal
            matched = True

    if not matched:
        total = 400

    return min(max(total, 50), 1500)


if __name__ == "__main__":
    mcp.run()
