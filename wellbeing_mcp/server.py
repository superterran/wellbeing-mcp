"""
wellbeing-mcp — FastMCP server.

Exposes tools for logging mood, weight, meals, and workouts,
plus a wellbeing://current resource that surfaces today's state
as background context in every Claude conversation.
"""

from fastmcp import FastMCP
from typing import Optional
from . import db

mcp = FastMCP(
    "wellbeing",
    instructions=(
        "Wellbeing context server. Provides personal health and mood data "
        "to inform conversation tone and suggestions. Read wellbeing://current "
        "at the start of each session for today's snapshot."
    ),
)

db.init_db()


# ---------------------------------------------------------------------------
# Resource: auto-loaded context
# ---------------------------------------------------------------------------

@mcp.resource("wellbeing://current")
def current_state() -> str:
    """Today's wellbeing snapshot — weight, workouts, calories, mood."""
    return db.build_current_snapshot()


@mcp.resource("wellbeing://profile")
def user_profile() -> str:
    """User background: history, goals, injury status, coaching notes."""
    import json
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


# ---------------------------------------------------------------------------
# Tools: logging
# ---------------------------------------------------------------------------

@mcp.tool()
def log_mood(
    score: Optional[int] = None,
    energy: Optional[int] = None,
    note: str = "",
) -> str:
    """
    Log current mood and/or energy level.

    Args:
        score:  Mood score 1–10 (1 = terrible, 10 = great). Optional.
        energy: Energy level 1–10. Optional.
        note:   Short description, e.g. "a bit frustrated" or "solid". Optional.
    """
    if score is None and energy is None and not note:
        return "Nothing logged — provide at least a score, energy, or note."
    db.log_mood(score, energy, note)
    parts = []
    if score is not None:
        parts.append(f"mood {score}/10")
    if energy is not None:
        parts.append(f"energy {energy}/10")
    if note:
        parts.append(f'"{note}"')
    return f"Logged: {', '.join(parts)}"


@mcp.tool()
def log_weight(weight_lbs: float, note: str = "") -> str:
    """
    Log a weight measurement in pounds.

    Args:
        weight_lbs: Weight in lbs.
        note:       Optional note (e.g. "morning, pre-coffee").
    """
    db.log_weight(weight_lbs, source="manual", note=note)
    profile = db.get_profile()
    goal = profile.get("goal_weight_lbs", 250)
    to_go = round(weight_lbs - goal, 1)
    return f"Logged {weight_lbs} lbs. {to_go} lbs to goal ({goal})."


@mcp.tool()
def log_meal(
    description: str,
    estimated_calories: Optional[int] = None,
    estimated_protein_g: Optional[int] = None,
    note: str = "",
) -> str:
    """
    Log a meal or snack. Describe it naturally — calories will be estimated if not provided.

    Args:
        description:         What you ate, e.g. "grilled chicken breast, rice, salad".
        estimated_calories:  Calorie estimate. If omitted, will be estimated from description.
        estimated_protein_g: Protein estimate in grams. Optional.
        note:                Any context, e.g. "was still hungry after".
    """
    # Rough estimation if not provided — good enough for trend tracking
    if estimated_calories is None:
        estimated_calories = _estimate_calories(description)

    db.log_meal(description, estimated_calories, estimated_protein_g, note)

    today_total = db.get_calories_today()
    profile = db.get_profile()
    target = profile.get("calorie_target", 2100)
    remaining = target - today_total

    result = f"Logged: {description} (~{estimated_calories} cal)"
    result += f"\nToday: {today_total} / {target} cal | {remaining} remaining"
    if remaining < 0:
        result += f" (over by {abs(remaining)})"
    return result


@mcp.tool()
def log_workout(
    workout_type: str,
    duration_minutes: Optional[int] = None,
    calories_burned: Optional[int] = None,
    note: str = "",
) -> str:
    """
    Log a completed workout.

    Args:
        workout_type:     Type of workout, e.g. "elliptical", "weights", "walk".
        duration_minutes: How long in minutes. Optional.
        calories_burned:  Active calories burned. Optional.
        note:             Any notes, e.g. "shoulder felt fine", "took it easy".
    """
    db.log_workout(workout_type, duration_minutes, calories_burned, note=note)
    parts = [workout_type]
    if duration_minutes:
        parts.append(f"{duration_minutes} min")
    if calories_burned:
        parts.append(f"{calories_burned} cal burned")
    return f"Logged workout: {', '.join(parts)}."


# ---------------------------------------------------------------------------
# Tools: retrieval / summary
# ---------------------------------------------------------------------------

@mcp.tool()
def get_today_summary() -> str:
    """Get today's full wellbeing snapshot."""
    return db.build_current_snapshot()


@mcp.tool()
def get_weekly_summary() -> str:
    """Get a summary of the past 7 days: workouts, weight trend, average calories."""
    from datetime import date, timedelta

    workouts = db.get_workouts_this_week()
    weight_trend = db.get_weight_trend(days=7)

    workout_lines = []
    for w in workouts:
        parts = [f"{w['workout_date']}: {w['type']}"]
        if w["duration_minutes"]:
            parts.append(f"{w['duration_minutes']}min")
        if w["calories_burned"]:
            parts.append(f"{w['calories_burned']}cal")
        workout_lines.append(" | ".join(parts))

    weight_lines = [f"{w['logged_at'][:10]}: {w['weight_lbs']} lbs" for w in weight_trend]

    lines = ["=== Past 7 Days ===", ""]
    lines.append(f"Workouts ({len(workouts)}):")
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
    Update a single field in the user profile.

    Args:
        field: Profile key, e.g. "goal_weight_lbs", "calorie_target", "injury".
        value: New value as a string (numbers will be converted automatically).
    """
    profile = db.get_profile()
    # Coerce numeric fields
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
    Very rough calorie estimation from natural language description.
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

    # If nothing matched, use a generic moderate meal estimate
    if not matched:
        total = 400

    # Cap to reasonable single-meal range
    return min(max(total, 50), 1500)


if __name__ == "__main__":
    mcp.run()
