"""
db.py — SQLite store for ephemeral gym session state only.

All persistent well-being data (weight, mood, meals, completed workouts)
lives in markdown daily notes via daily.py. SQLite is used only for:

  - gym_session: tracks an active session from start to finish
  - exercise_log: individual exercise sets logged during a session
  - apple_health_raw: raw payloads from Health Auto Export webhook
  - profile: user background stored as JSON (not in vault for privacy)

When a gym session finishes, its summary is written to the vault and
the SQLite rows become historical reference only.
"""

import json
import sqlite3
from datetime import datetime
from pathlib import Path

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
            CREATE TABLE IF NOT EXISTS gym_session (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                started_at    TEXT NOT NULL DEFAULT (datetime('now')),
                finished_at   TEXT,
                session_type  TEXT,
                notes         TEXT,
                vault_path    TEXT,
                total_minutes INTEGER
            );

            CREATE TABLE IF NOT EXISTS exercise_log (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id  INTEGER REFERENCES gym_session(id),
                logged_at   TEXT NOT NULL DEFAULT (datetime('now')),
                name        TEXT NOT NULL,
                set_number  INTEGER,
                reps        INTEGER,
                weight_lbs  REAL,
                rpe         INTEGER,
                modified    INTEGER DEFAULT 0,
                note        TEXT
            );

            CREATE TABLE IF NOT EXISTS apple_health_raw (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                received_at TEXT NOT NULL DEFAULT (datetime('now')),
                payload     TEXT NOT NULL
            );
        """)


# --- Profile ---

def get_profile() -> dict:
    if PROFILE_PATH.exists():
        return json.loads(PROFILE_PATH.read_text())
    return DEFAULT_PROFILE


def save_profile(profile: dict) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    PROFILE_PATH.write_text(json.dumps(profile, indent=2))


# --- Gym sessions ---

def start_gym_session(session_type: str) -> int:
    with get_db() as conn:
        cur = conn.execute(
            "INSERT INTO gym_session (session_type) VALUES (?)",
            (session_type,),
        )
        return cur.lastrowid


def get_active_session() -> dict | None:
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM gym_session WHERE finished_at IS NULL ORDER BY started_at DESC LIMIT 1"
        ).fetchone()
        return dict(row) if row else None


def finish_gym_session(session_id: int, notes: str = "", vault_path: str = "") -> dict:
    with get_db() as conn:
        row = conn.execute("SELECT started_at FROM gym_session WHERE id = ?", (session_id,)).fetchone()
        started = row["started_at"] if row else None

    total_minutes = None
    if started:
        elapsed = datetime.now() - datetime.fromisoformat(started)
        total_minutes = int(elapsed.total_seconds() / 60)

    with get_db() as conn:
        conn.execute(
            "UPDATE gym_session SET finished_at = datetime('now'), notes = ?, vault_path = ?, total_minutes = ? WHERE id = ?",
            (notes or None, vault_path or None, total_minutes, session_id),
        )
    return {"total_minutes": total_minutes}


def get_last_gym_session() -> dict | None:
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM gym_session WHERE finished_at IS NOT NULL ORDER BY finished_at DESC LIMIT 1"
        ).fetchone()
        return dict(row) if row else None


# --- Exercise log ---

def log_exercise(
    session_id: int,
    name: str,
    set_number: int | None = None,
    reps: int | None = None,
    weight_lbs: float | None = None,
    rpe: int | None = None,
    modified: bool = False,
    note: str = "",
) -> int:
    with get_db() as conn:
        cur = conn.execute(
            """INSERT INTO exercise_log
               (session_id, name, set_number, reps, weight_lbs, rpe, modified, note)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (session_id, name, set_number, reps, weight_lbs, rpe, int(modified), note or None),
        )
        return cur.lastrowid


def get_session_exercises(session_id: int) -> list[dict]:
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM exercise_log WHERE session_id = ? ORDER BY logged_at ASC",
            (session_id,),
        ).fetchall()
        return [dict(r) for r in rows]


# --- Apple Health raw storage ---

def store_apple_health_raw(payload: dict) -> None:
    with get_db() as conn:
        conn.execute(
            "INSERT INTO apple_health_raw (payload) VALUES (?)",
            (json.dumps(payload),),
        )
