"""Tests for wellbeing_mcp.db — gym session state only."""

import pytest
from unittest.mock import patch


@pytest.fixture(autouse=True)
def isolated_db(tmp_path):
    """Redirect DB and profile to a temp directory for each test."""
    import wellbeing_mcp.db as db_module

    db_path = tmp_path / "wellbeing.db"
    profile_path = tmp_path / "profile.json"

    with (
        patch.object(db_module, "DATA_DIR", tmp_path),
        patch.object(db_module, "DB_PATH", db_path),
        patch.object(db_module, "PROFILE_PATH", profile_path),
    ):
        db_module.init_db()
        yield db_module


# --- Profile ---

def test_get_default_profile(isolated_db):
    profile = isolated_db.get_profile()
    assert profile["name"] == "Doug"
    assert profile["goal_weight_lbs"] == 250
    assert profile["calorie_target"] == 2100


def test_save_and_reload_profile(isolated_db):
    db = isolated_db
    profile = db.get_profile()
    profile["goal_weight_lbs"] = 245
    db.save_profile(profile)
    reloaded = db.get_profile()
    assert reloaded["goal_weight_lbs"] == 245


# --- Gym sessions ---

def test_start_gym_session_returns_id(isolated_db):
    db = isolated_db
    session_id = db.start_gym_session("A-push")
    assert isinstance(session_id, int)
    assert session_id > 0


def test_get_active_session(isolated_db):
    db = isolated_db
    db.start_gym_session("cardio")
    session = db.get_active_session()
    assert session is not None
    assert session["session_type"] == "cardio"
    assert session["finished_at"] is None


def test_get_active_session_none_when_empty(isolated_db):
    assert isolated_db.get_active_session() is None


def test_finish_gym_session(isolated_db):
    db = isolated_db
    sid = db.start_gym_session("B-pull-lower")
    result = db.finish_gym_session(sid, notes="felt good")
    assert "total_minutes" in result

    # Session should no longer be active
    assert db.get_active_session() is None


def test_get_last_gym_session(isolated_db):
    db = isolated_db
    sid = db.start_gym_session("A-push")
    db.finish_gym_session(sid)
    last = db.get_last_gym_session()
    assert last is not None
    assert last["session_type"] == "A-push"
    assert last["finished_at"] is not None


def test_get_last_gym_session_none_when_empty(isolated_db):
    assert isolated_db.get_last_gym_session() is None


# --- Exercise log ---

def test_log_exercise(isolated_db):
    db = isolated_db
    sid = db.start_gym_session("A-push")
    ex_id = db.log_exercise(sid, "Leg Press", set_number=1, reps=15, weight_lbs=120.0, rpe=7)
    assert isinstance(ex_id, int)

    exercises = db.get_session_exercises(sid)
    assert len(exercises) == 1
    assert exercises[0]["name"] == "Leg Press"
    assert exercises[0]["reps"] == 15
    assert exercises[0]["weight_lbs"] == 120.0


def test_log_exercise_multiple_sets(isolated_db):
    db = isolated_db
    sid = db.start_gym_session("B-pull-lower")
    for i in range(1, 4):
        db.log_exercise(sid, "Assisted Pull-Up Machine", set_number=i, reps=10)
    exercises = db.get_session_exercises(sid)
    assert len(exercises) == 3


def test_get_session_exercises_empty(isolated_db):
    db = isolated_db
    sid = db.start_gym_session("cardio")
    assert db.get_session_exercises(sid) == []


def test_log_exercise_modified_flag(isolated_db):
    db = isolated_db
    sid = db.start_gym_session("A-push")
    db.log_exercise(sid, "Cable Row (seated)", modified=True, note="sub for bench press")
    exercises = db.get_session_exercises(sid)
    assert exercises[0]["modified"] == 1


# --- Apple Health raw storage ---

def test_store_apple_health_raw(isolated_db):
    db = isolated_db
    payload = {"data": {"metrics": [], "workouts": []}}
    # Should not raise
    db.store_apple_health_raw(payload)
