"""
SQLite storage and user profile for wellbeing-mcp.
"""

import sqlite3
import json
from pathlib import Path
from datetime import datetime, date, timedelta
from typing import Optional

DATA_DIR = Path.home() / ".local" / "share" / "wellbeing-mcp"
DB_PATH = DATA_DIR / "wellbeing.db"
PROFILE_PATH = DATA_DIR / "profile.json"

DEFAULT_PROFILE = {
    "name": "Doug",
    "age": 41,
    "sex": "male",
    "current_weight_estimate_lbs": 280,
    "goal_weight_lbs": 250,
    "calorie_target": 2100,
    "history": (
        "Lost over 200 lbs. Has maintained significant weight loss. "
        "Knows exactly how to do this — not a beginner. Treat accordingly."
    ),
    "injury": (
        "Right shoulder tendon strain, mostly healed as of early 2026. "
        "Avoid heavy upper body pressing movements. "
        "Elliptical and lower body work are fine."
    ),
    "illness_recovery": "Was sick for about a month around March 2026. Now recovered.",
    "preferred_cardio": "elliptical",
    "main_diet_challenge": "snacking",
    "diet_baseline": "Eats a salad daily. Snacking is the main issue.",
    "scale_note": (
        "Has significant excess skin from major weight loss, plus substantial muscle mass "
        "from heavy lifting. Scale weight is one data point, not the whole picture. "
        "Daily weigh-in is for trend data, not gospel."
    ),
    "partner": "Kaylin",
    "coaching_tone": (
        "Data-driven and practical. No cheerleading. No hollow praise. "
        "Treat as an experienced person who knows the process — just needs accountability "
        "and to get back on track. Be direct and brief. Notice patterns."
    ),
}


def get_db() -> sqlite3.Connection:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db() -> None:
    with get_db() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS mood_log (
                id        INTEGER PRIMARY KEY AUTOINCREMENT,
                logged_at TEXT NOT NULL DEFAULT (datetime('now')),
                score     INTEGER,        -- 1-10
                energy    INTEGER,        -- 1-10
                note      TEXT
            );

            CREATE TABLE IF NOT EXISTS weight_log (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                logged_at  TEXT NOT NULL DEFAULT (datetime('now')),
                weight_lbs REAL NOT NULL,
                source     TEXT DEFAULT 'manual',  -- 'manual' or 'apple_health'
                note       TEXT
            );

            CREATE TABLE IF NOT EXISTS meal_log (
                id                 INTEGER PRIMARY KEY AUTOINCREMENT,
                logged_at          TEXT NOT NULL DEFAULT (datetime('now')),
                description        TEXT NOT NULL,
                estimated_calories INTEGER,
                estimated_protein_g INTEGER,
                note               TEXT
            );

            CREATE TABLE IF NOT EXISTS workout_log (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                logged_at        TEXT NOT NULL DEFAULT (datetime('now')),
                workout_date     TEXT NOT NULL DEFAULT (date('now')),
                type             TEXT NOT NULL,
                duration_minutes INTEGER,
                calories_burned  INTEGER,
                source           TEXT DEFAULT 'manual',  -- 'manual' or 'apple_health'
                note             TEXT
            );

            CREATE TABLE IF NOT EXISTS apple_health_raw (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                received_at TEXT NOT NULL DEFAULT (datetime('now')),
                payload     TEXT NOT NULL  -- raw JSON from Health Auto Export
            );
        """)


def get_profile() -> dict:
    if PROFILE_PATH.exists():
        return json.loads(PROFILE_PATH.read_text())
    return DEFAULT_PROFILE


def save_profile(profile: dict) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    PROFILE_PATH.write_text(json.dumps(profile, indent=2))


# --- Mood ---

def log_mood(score: Optional[int], energy: Optional[int], note: str = "") -> int:
    with get_db() as conn:
        cur = conn.execute(
            "INSERT INTO mood_log (score, energy, note) VALUES (?, ?, ?)",
            (score, energy, note or None),
        )
        return cur.lastrowid


def get_latest_mood() -> Optional[dict]:
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM mood_log ORDER BY logged_at DESC LIMIT 1"
        ).fetchone()
        return dict(row) if row else None


# --- Weight ---

def log_weight(weight_lbs: float, source: str = "manual", note: str = "") -> int:
    with get_db() as conn:
        cur = conn.execute(
            "INSERT INTO weight_log (weight_lbs, source, note) VALUES (?, ?, ?)",
            (weight_lbs, source, note or None),
        )
        return cur.lastrowid


def get_weight_trend(days: int = 14) -> list[dict]:
    since = (datetime.now() - timedelta(days=days)).isoformat()
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM weight_log WHERE logged_at >= ? ORDER BY logged_at ASC",
            (since,),
        ).fetchall()
        return [dict(r) for r in rows]


def get_latest_weight() -> Optional[dict]:
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM weight_log ORDER BY logged_at DESC LIMIT 1"
        ).fetchone()
        return dict(row) if row else None


# --- Meals ---

def log_meal(
    description: str,
    estimated_calories: Optional[int] = None,
    estimated_protein_g: Optional[int] = None,
    note: str = "",
) -> int:
    with get_db() as conn:
        cur = conn.execute(
            "INSERT INTO meal_log (description, estimated_calories, estimated_protein_g, note) VALUES (?, ?, ?, ?)",
            (description, estimated_calories, estimated_protein_g, note or None),
        )
        return cur.lastrowid


def get_meals_today() -> list[dict]:
    today = date.today().isoformat()
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM meal_log WHERE date(logged_at) = ? ORDER BY logged_at ASC",
            (today,),
        ).fetchall()
        return [dict(r) for r in rows]


def get_calories_today() -> int:
    today = date.today().isoformat()
    with get_db() as conn:
        row = conn.execute(
            "SELECT COALESCE(SUM(estimated_calories), 0) as total FROM meal_log WHERE date(logged_at) = ?",
            (today,),
        ).fetchone()
        return row["total"]


# --- Workouts ---

def log_workout(
    workout_type: str,
    duration_minutes: Optional[int] = None,
    calories_burned: Optional[int] = None,
    source: str = "manual",
    note: str = "",
    workout_date: Optional[str] = None,
) -> int:
    wdate = workout_date or date.today().isoformat()
    with get_db() as conn:
        cur = conn.execute(
            """INSERT INTO workout_log
               (workout_date, type, duration_minutes, calories_burned, source, note)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (wdate, workout_type, duration_minutes, calories_burned, source, note or None),
        )
        return cur.lastrowid


def get_workouts_this_week() -> list[dict]:
    week_ago = (date.today() - timedelta(days=7)).isoformat()
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM workout_log WHERE workout_date >= ? ORDER BY workout_date DESC",
            (week_ago,),
        ).fetchall()
        return [dict(r) for r in rows]


def get_last_workout() -> Optional[dict]:
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM workout_log ORDER BY workout_date DESC, logged_at DESC LIMIT 1"
        ).fetchone()
        return dict(row) if row else None


# --- Apple Health ingestion ---

def ingest_apple_health(payload: dict) -> dict:
    """
    Parse Health Auto Export webhook payload and store weight + workout data.
    Returns summary of what was ingested.
    """
    ingested = {"weights": 0, "workouts": 0}

    with get_db() as conn:
        conn.execute(
            "INSERT INTO apple_health_raw (payload) VALUES (?)",
            (json.dumps(payload),),
        )

    metrics = payload.get("data", {}).get("metrics", [])
    for metric in metrics:
        name = metric.get("name", "")
        if name in ("body_mass", "weight_body_mass"):
            for entry in metric.get("data", []):
                qty = entry.get("qty")
                dt = entry.get("date", "")
                if qty:
                    log_weight(float(qty), source="apple_health")
                    ingested["weights"] += 1

    workouts = payload.get("data", {}).get("workouts", [])
    for w in workouts:
        wtype = w.get("name", "Unknown")
        start = w.get("start", "")
        duration = w.get("duration")
        burned = None
        active = w.get("activeEnergyBurned", {})
        if isinstance(active, dict):
            burned = active.get("qty")

        wdate = start[:10] if start else date.today().isoformat()
        duration_min = int(float(duration)) if duration else None
        calories = int(float(burned)) if burned else None

        # Avoid duplicates: skip if same type + date already exists from apple_health
        with get_db() as conn:
            exists = conn.execute(
                "SELECT 1 FROM workout_log WHERE workout_date = ? AND type = ? AND source = 'apple_health'",
                (wdate, wtype),
            ).fetchone()
            if not exists:
                log_workout(wtype, duration_min, calories, source="apple_health", workout_date=wdate)
                ingested["workouts"] += 1

    return ingested


# --- Summary helpers ---

def build_current_snapshot() -> str:
    profile = get_profile()
    today = date.today().isoformat()

    # Weight
    latest_weight = get_latest_weight()
    weight_trend = get_weight_trend(days=14)
    if latest_weight:
        lw = latest_weight["weight_lbs"]
        goal = profile.get("goal_weight_lbs", 250)
        to_go = round(lw - goal, 1)
        weight_line = f"{lw} lbs | {to_go} lbs to goal ({goal})"
        if len(weight_trend) >= 2:
            first = weight_trend[0]["weight_lbs"]
            last = weight_trend[-1]["weight_lbs"]
            delta = round(last - first, 1)
            direction = "↓" if delta < 0 else "↑" if delta > 0 else "→"
            weight_line += f" | 2-week trend: {direction}{abs(delta)} lbs"
    else:
        estimate = profile.get("current_weight_estimate_lbs", "unknown")
        goal = profile.get("goal_weight_lbs", 250)
        weight_line = f"not logged yet (estimated ~{estimate} lbs | goal: {goal})"

    # Workouts
    last_workout = get_last_workout()
    workouts_week = get_workouts_this_week()
    if last_workout:
        lw_date = last_workout["workout_date"]
        days_ago = (date.today() - date.fromisoformat(lw_date)).days
        ago_str = "today" if days_ago == 0 else f"{days_ago}d ago"
        workout_line = f"{len(workouts_week)} this week | last: {last_workout['type']} ({ago_str})"
    else:
        workout_line = "none logged yet"

    # Calories
    calories_today = get_calories_today()
    meals_today = get_meals_today()
    target = profile.get("calorie_target", 2100)
    if calories_today > 0:
        remaining = target - calories_today
        cal_line = f"{calories_today} / {target} cal | {remaining} remaining"
    else:
        cal_line = f"0 / {target} — nothing logged today"

    # Mood
    mood = get_latest_mood()
    if mood:
        logged_at = mood["logged_at"][:16]
        parts = []
        if mood["score"]:
            parts.append(f"mood {mood['score']}/10")
        if mood["energy"]:
            parts.append(f"energy {mood['energy']}/10")
        if mood["note"]:
            parts.append(f'"{mood["note"]}"')
        mood_line = f"{', '.join(parts)} (logged {logged_at})"
    else:
        mood_line = "not logged today"

    # Injury status
    injury = profile.get("injury", "")
    injury_line = "Right shoulder tendon — mostly healed, still flares up when pushed"

    snapshot = f"""[Wellbeing — {today}]
Weight:    {weight_line}
Workouts:  {workout_line}
Calories:  {cal_line}
Mood:      {mood_line}
Injury:    {injury_line}
Context:   Returning after ~4 weeks off (injury + illness). Getting back to elliptical + tracking.
Goal:      {profile.get('goal_weight_lbs', 250)} lbs | Calorie target: {target}/day"""

    return snapshot
