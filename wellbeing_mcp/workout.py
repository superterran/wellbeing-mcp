"""
workout.py — workout planning and gym session logic.

Determines today's session type (A/B), applies shoulder modifications,
handles equipment availability substitutions, and formats plans
conversationally for gym-floor use.
"""

from datetime import date, datetime

from . import db

# ---------------------------------------------------------------------------
# Equipment registry
# ---------------------------------------------------------------------------

# Maps exercise name (lowercase) → equipment key required
EQUIPMENT_REQUIRED: dict[str, str | None] = {
    "elliptical": "elliptical",
    "assisted pull-up machine": "pull_up_machine",
    "lat pulldown machine": "lat_pulldown",
    "single-arm dumbbell row": "dumbbells",
    "leg press": "leg_press",
    "machine-assisted squats": "smith_machine",
    "cable row (seated)": "cable_machine",
    "reverse pec deck": "pec_deck",
    "face pull (cable)": "cable_machine",
    "stair machine": "stair_machine",
    "rowing machine": "rowing_machine",
    "machine bench press": "chest_press_machine",
    "pec deck": "pec_deck",
    "lateral raise": "dumbbells",
    "goblet squat": "dumbbells",
    "pushups (knees)": None,  # bodyweight
    "situps / crunches": None,
    "plank": None,
}

# Equipment substitutions: exercise name (lowercase) → list of (substitute_name, rationale)
EQUIPMENT_SUBS: dict[str, list[tuple[str, str]]] = {
    "assisted pull-up machine": [
        ("Lat Pulldown Machine", "Same lat engagement, no assist needed — adjust weight"),
        ("Single-Arm Dumbbell Row", "Good fallback pull if pulldown is also busy"),
    ],
    "lat pulldown machine": [
        ("Assisted Pull-Up Machine", "Same movement pattern, assisted"),
        ("Single-Arm Dumbbell Row", "Unilateral pull, effective substitute"),
    ],
    "leg press": [
        ("Machine-Assisted Squats", "Similar quad load — drop weight, focus on depth"),
        ("Goblet Squat", "Dumbbell, no machine needed. 3×15"),
    ],
    "machine-assisted squats": [
        ("Goblet Squat", "Dumbbell, anywhere. 3×15"),
        ("Leg Press", "Swap order if leg press is free"),
    ],
    "cable row (seated)": [
        ("Single-Arm Dumbbell Row", "Same pull pattern, no cable needed"),
        ("Resistance Band Row", "If dumbbells are also unavailable"),
    ],
    "face pull (cable)": [
        ("Reverse Pec Deck", "Rear delt focus, no cable"),
        ("Band Pull-Apart", "Light band, shoulder safe"),
    ],
    "reverse pec deck": [
        ("Face Pull (cable)", "Rear delt, cable version"),
        ("Band Pull-Apart", "Shoulder safe bodyweight option"),
    ],
    "stair machine": [
        ("Incline Treadmill", "10–15% grade, brisk walk, 10–15 min"),
        ("Extra Elliptical", "Extend elliptical time by 10 min instead"),
    ],
    "rowing machine": [
        ("Elliptical", "Extend elliptical time if rowing machine is taken"),
        ("Stair Machine", "Good cardio swap"),
    ],
    "elliptical": [
        ("Rowing Machine", "Full-body cardio, easier on joints"),
        ("Stair Machine", "Higher intensity, good substitute"),
    ],
}

# ---------------------------------------------------------------------------
# Routine definitions
# ---------------------------------------------------------------------------

# Exercises flagged as shoulder-risky (right shoulder tendon)
SHOULDER_RISKY = {
    "machine bench press",
    "bench press",
    "pec deck",
    "lateral raise",
    "lateral raises",
    "overhead press",
    "shoulder press",
    "dumbbell press",
}

# Substitutions when shoulder is flagged
SHOULDER_SUBS = {
    "machine bench press": ("Cable Row (seated)", "Pulls instead of pushes — shoulder safe"),
    "pec deck": ("Reverse Pec Deck", "Rear-delt focus, no shoulder impingement"),
    "lateral raise": ("Face Pull (cable)", "Rotator cuff safe, rear delt"),
    "lateral raises": ("Face Pull (cable)", "Rotator cuff safe, rear delt"),
    "bench press": ("Cable Row (seated)", "Pulls instead of pushes"),
}

ROUTINE = {
    "A-push": {
        "label": "Workout A — Push Focus",
        "exercises": [
            {
                "name": "Elliptical",
                "sets": 1,
                "reps": None,
                "weight": None,
                "note": "20–30 min moderate pace, HR ~120–130 bpm. Priority — do this even if short on time.",
            },
            {
                "name": "Machine Bench Press",
                "sets": 3,
                "reps": 12,
                "weight": "30–40 lbs",
                "note": "Light to start — shoulder test. Stop if any pain.",
            },
            {
                "name": "Pec Deck",
                "sets": 3,
                "reps": 12,
                "weight": None,
                "note": "Controlled squeeze. Skip if shoulder complains.",
            },
            {
                "name": "Lateral Raise",
                "sets": 3,
                "reps": 12,
                "weight": "8–10 lbs",
                "note": "Very light. Skip entirely if shoulder is off.",
            },
            {
                "name": "Pushups (knees)",
                "sets": 3,
                "reps": 12,
                "weight": None,
                "note": "Mat. Good form over speed.",
            },
            {
                "name": "Situps / Crunches",
                "sets": 3,
                "reps": 20,
                "weight": None,
                "note": "Mat. Core endurance.",
            },
            {
                "name": "Stair Machine",
                "sets": 1,
                "reps": None,
                "weight": None,
                "note": "10–15 min finisher, steady climb.",
            },
        ],
    },
    "B-pull-lower": {
        "label": "Workout B — Pull + Lower Focus",
        "exercises": [
            {
                "name": "Elliptical",
                "sets": 1,
                "reps": None,
                "weight": None,
                "note": "20 min warmup, moderate pace.",
            },
            {
                "name": "Assisted Pull-Up Machine",
                "sets": 3,
                "reps": 10,
                "weight": None,
                "note": "Controlled descent. No shoulder pain expected here.",
            },
            {
                "name": "Single-Arm Dumbbell Row",
                "sets": 3,
                "reps": 12,
                "weight": "35 lbs",
                "note": "Bench at 30° angle. This is shoulder-safe — elbow stays tucked.",
            },
            {
                "name": "Leg Press",
                "sets": 3,
                "reps": 15,
                "weight": None,
                "note": "Moderate resistance. Push through heels.",
            },
            {
                "name": "Machine-Assisted Squats",
                "sets": 3,
                "reps": 15,
                "weight": "70–80 lbs",
                "note": "Lower than previous weight — we're coming back fresh.",
            },
            {
                "name": "Plank",
                "sets": 3,
                "reps": None,
                "weight": None,
                "note": "30s hold. Core stability.",
            },
            {
                "name": "Stair Machine",
                "sets": 1,
                "reps": None,
                "weight": None,
                "note": "10 min finisher.",
            },
        ],
    },
    "cardio": {
        "label": "Cardio Day",
        "exercises": [
            {
                "name": "Elliptical",
                "sets": 1,
                "reps": None,
                "weight": None,
                "note": "30–40 min. This is the one. Intervals optional: 1 min hard / 1 min easy.",
            },
            {
                "name": "Rowing Machine",
                "sets": 1,
                "reps": None,
                "weight": None,
                "note": "5–10 min, full-range controlled strokes.",
            },
            {
                "name": "Stair Machine",
                "sets": 1,
                "reps": None,
                "weight": None,
                "note": "10 min steady finisher.",
            },
        ],
    },
}


# ---------------------------------------------------------------------------
# Session type determination
# ---------------------------------------------------------------------------


def determine_session_type() -> tuple[str, str]:
    """
    Returns (session_type, rationale) based on last completed session.

    Rotation: A → B → A → B (Monday–Wednesday–Friday)
    If it's been 7+ days since last session, start with cardio to ease back in.
    """
    last = db.get_last_gym_session()

    if last is None:
        return "cardio", "First session in the log — starting with cardio to ease back in."

    last_type = last.get("session_type", "")
    last_date_str = last.get("finished_at", "") or last.get("started_at", "")

    try:
        last_date = datetime.fromisoformat(last_date_str).date()
        days_since = (date.today() - last_date).days
    except (ValueError, TypeError):
        days_since = 99

    if days_since >= 7:
        return (
            "cardio",
            f"It's been {days_since} days since your last session. Starting with cardio.",
        )

    if last_type == "A-push":
        return "B-pull-lower", "Last session was A (push). Today: B (pull + lower)."
    elif last_type == "B-pull-lower":
        return "A-push", "Last session was B (pull/lower). Today: A (push)."
    elif last_type == "cardio":
        return "A-push", "Last session was cardio. Starting A/B cycle: A (push) today."
    else:
        return "A-push", "Defaulting to A (push)."


# ---------------------------------------------------------------------------
# Plan formatting
# ---------------------------------------------------------------------------


def _apply_shoulder_mods(exercises: list[dict], shoulder_ok: bool) -> list[dict]:
    """Apply shoulder modifications if needed. Returns modified exercise list."""
    result = []
    for ex in exercises:
        name_lower = ex["name"].lower()
        if not shoulder_ok and name_lower in SHOULDER_RISKY:
            if name_lower in SHOULDER_SUBS:
                sub_name, sub_note = SHOULDER_SUBS[name_lower]
                result.append(
                    {
                        **ex,
                        "name": sub_name,
                        "note": f"[SUB for {ex['name']}] {sub_note}",
                        "modified": True,
                    }
                )
            else:
                # Skip entirely
                result.append(
                    {
                        **ex,
                        "note": f"⚠️ SKIPPED — shoulder. Original: {ex['note']}",
                        "modified": True,
                        "skip": True,
                    }
                )
        else:
            result.append({**ex, "modified": False})
    return result


def build_workout_plan(session_type: str, shoulder_ok: bool = True) -> dict:
    """
    Build a full workout plan for the given session type.
    Returns dict with label, exercises (possibly modified), and notes.
    """
    template = ROUTINE.get(session_type, ROUTINE["cardio"])
    exercises = _apply_shoulder_mods(template["exercises"], shoulder_ok)
    return {
        "session_type": session_type,
        "label": template["label"],
        "exercises": exercises,
        "shoulder_modified": not shoulder_ok,
    }


def format_plan_for_conversation(plan: dict, rationale: str = "", days_since_last: int = 0) -> str:
    """
    Format a workout plan as a conversational prompt for the gym floor.
    """
    lines = []
    lines.append(f"## {plan['label']}")
    lines.append("")

    if rationale:
        lines.append(f"_{rationale}_")
        lines.append("")

    if days_since_last >= 7:
        lines.append(
            f"> Coming back after {days_since_last} days off. Weights are dialed back — form over load today."
        )
        lines.append("")

    if plan.get("shoulder_modified"):
        lines.append(
            "> ⚠️ Shoulder modifications applied. Flagged exercises have been substituted or removed."
        )
        lines.append("")

    lines.append("### Exercises")
    lines.append("")

    for i, ex in enumerate(plan["exercises"], 1):
        if ex.get("skip"):
            continue
        sets_str = f"{ex['sets']}×" if ex.get("sets") and ex["sets"] > 1 else ""
        reps_str = str(ex.get("reps", "")) if ex.get("reps") else "timed"
        weight_str = f" @ {ex['weight']}" if ex.get("weight") else ""
        modified_flag = " ⚠️ modified" if ex.get("modified") else ""

        lines.append(f"**{i}. {ex['name']}**{modified_flag}")
        if sets_str or reps_str or weight_str:
            lines.append(f"   {sets_str}{reps_str}{weight_str}")
        if ex.get("note"):
            lines.append(f"   _{ex['note']}_")
        lines.append("")

    lines.append("---")
    lines.append("Tell me when you're done with each exercise and I'll log it and move you along.")
    lines.append(
        "Say **'done'**, **'skip'**, or give me the actual weight/reps if different from the plan."
    )

    return "\n".join(lines)


def get_days_since_last_session() -> int:
    last = db.get_last_gym_session()
    if not last:
        return 999
    last_date_str = last.get("finished_at", "") or last.get("started_at", "")
    try:
        last_date = datetime.fromisoformat(last_date_str).date()
        return (date.today() - last_date).days
    except (ValueError, TypeError):
        return 999


def summarize_session(session_id: int) -> str:
    """Generate a plain-text summary of a completed session for the vault note."""
    session = None
    with db.get_db() as conn:
        row = conn.execute("SELECT * FROM gym_session WHERE id = ?", (session_id,)).fetchone()
        if row:
            session = dict(row)

    if not session:
        return "Session not found."

    exercises = db.get_session_exercises(session_id)
    duration = session.get("total_minutes")
    session_type = session.get("session_type", "unknown")

    lines = [f"Completed {session_type} session"]
    if duration:
        lines.append(f"Duration: {duration} min")
    lines.append(f"Exercises logged: {len(exercises)}")
    modified = [e for e in exercises if e.get("modified")]
    if modified:
        lines.append(f"Modified exercises (shoulder): {len(modified)}")
    return " | ".join(lines)


# ---------------------------------------------------------------------------
# Equipment-aware planning
# ---------------------------------------------------------------------------


def apply_equipment_mods(exercises: list[dict], unavailable: list[str]) -> list[dict]:
    """
    Substitute or skip exercises whose required equipment is listed as unavailable.
    unavailable is a list of plain-name equipment strings (case-insensitive),
    e.g. ["cable machine", "stair machine"].
    """
    unavail_lower = {u.lower() for u in unavailable}
    result = []
    for ex in exercises:
        name_lower = ex["name"].lower()
        required = EQUIPMENT_REQUIRED.get(name_lower)
        # Normalise equipment key for comparison (underscores → spaces, vice versa)
        if required and (required in unavail_lower or required.replace("_", " ") in unavail_lower):
            subs = EQUIPMENT_SUBS.get(name_lower, [])
            if subs:
                sub_name, sub_note = subs[0]
                result.append(
                    {
                        **ex,
                        "name": sub_name,
                        "note": f"[SUB — {ex['name']} unavailable] {sub_note}",
                        "modified": True,
                    }
                )
            else:
                result.append(
                    {
                        **ex,
                        "note": f"⚠️ SKIPPED — {ex['name']} equipment unavailable. {ex.get('note', '')}",
                        "modified": True,
                        "skip": True,
                    }
                )
        else:
            result.append(ex)
    return result


def suggest_substitute(exercise_name: str) -> str:
    """
    Return substitute options for a given exercise, formatted for conversation.
    """
    subs = EQUIPMENT_SUBS.get(exercise_name.lower())
    if not subs:
        return f"No specific substitutes on file for {exercise_name}. Ask the coach."
    lines = [f"Substitutes for **{exercise_name}**:"]
    for i, (name, rationale) in enumerate(subs, 1):
        lines.append(f"{i}. **{name}** — {rationale}")
    return "\n".join(lines)


def get_next_exercise(session_id: int, session_type: str, shoulder_ok: bool = True) -> str:
    """
    Return the next exercise not yet started in this session, based on the plan.
    Compares logged exercise names against the planned order.
    """
    template = ROUTINE.get(session_type, ROUTINE["cardio"])
    planned = _apply_shoulder_mods(template["exercises"], shoulder_ok)
    planned_names = [ex["name"].lower() for ex in planned if not ex.get("skip")]

    logged = db.get_session_exercises(session_id)
    logged_names = {ex["name"].lower() for ex in logged}

    for ex in planned:
        if ex.get("skip"):
            continue
        if ex["name"].lower() not in logged_names:
            sets_str = f"{ex['sets']}×" if ex.get("sets") and ex["sets"] > 1 else ""
            reps_str = str(ex.get("reps", "")) if ex.get("reps") else "timed"
            weight_str = f" @ {ex['weight']}" if ex.get("weight") else ""
            lines = [f"**Next: {ex['name']}**"]
            if sets_str or reps_str:
                lines.append(f"{sets_str}{reps_str}{weight_str}")
            if ex.get("note"):
                lines.append(f"_{ex['note']}_")
            remaining = sum(1 for n in planned_names if n not in logged_names)
            lines.append(f"({remaining} exercise{'s' if remaining != 1 else ''} left in plan)")
            return "\n".join(lines)

    return "All planned exercises logged. Nice work — ready to finish the session?"


def format_session_status(session_id: int, session_type: str, shoulder_ok: bool = True) -> str:
    """
    Return a conversational summary of where we are in the current session.
    """
    from datetime import datetime as dt

    session = None
    with db.get_db() as conn:
        row = conn.execute("SELECT * FROM gym_session WHERE id = ?", (session_id,)).fetchone()
        if row:
            session = dict(row)

    if not session:
        return "No active session."

    exercises = db.get_session_exercises(session_id)
    started = session.get("started_at", "")
    elapsed = ""
    if started:
        try:
            elapsed_min = int((dt.now() - dt.fromisoformat(started)).total_seconds() / 60)
            elapsed = f"{elapsed_min} min in"
        except (ValueError, TypeError):
            pass

    template = ROUTINE.get(session_type, ROUTINE["cardio"])
    planned = _apply_shoulder_mods(template["exercises"], shoulder_ok)
    total = sum(1 for ex in planned if not ex.get("skip"))
    done_names = {ex["name"].lower() for ex in exercises}
    done = sum(1 for ex in planned if not ex.get("skip") and ex["name"].lower() in done_names)

    lines = [
        f"**{template['label']}** | {elapsed}",
        f"Progress: {done}/{total} exercises",
    ]
    if exercises:
        last = exercises[-1]
        parts = [last["name"]]
        if last.get("set_number"):
            parts.append(f"set {last['set_number']}")
        if last.get("reps"):
            parts.append(f"{last['reps']} reps")
        if last.get("weight_lbs"):
            parts.append(f"@ {last['weight_lbs']} lbs")
        lines.append(f"Last logged: {' | '.join(parts)}")
    return "\n".join(lines)
