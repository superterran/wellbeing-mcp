"""Tests for wellbeing_mcp.db"""

import pytest
import tempfile
from pathlib import Path
from unittest.mock import patch
from datetime import date


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


# --- Mood ---

def test_log_and_retrieve_mood(isolated_db):
    db = isolated_db
    db.log_mood(score=7, energy=6, note="feeling okay")
    mood = db.get_latest_mood()
    assert mood is not None
    assert mood["score"] == 7
    assert mood["energy"] == 6
    assert mood["note"] == "feeling okay"


def test_log_mood_partial(isolated_db):
    db = isolated_db
    db.log_mood(score=5, energy=None, note="")
    mood = db.get_latest_mood()
    assert mood["score"] == 5
    assert mood["energy"] is None


def test_get_latest_mood_returns_none_when_empty(isolated_db):
    assert isolated_db.get_latest_mood() is None


# --- Weight ---

def test_log_and_retrieve_weight(isolated_db):
    db = isolated_db
    db.log_weight(278.5)
    w = db.get_latest_weight()
    assert w is not None
    assert w["weight_lbs"] == 278.5
    assert w["source"] == "manual"


def test_weight_trend(isolated_db):
    db = isolated_db
    db.log_weight(282.0)
    db.log_weight(280.5)
    db.log_weight(279.0)
    trend = db.get_weight_trend(days=7)
    assert len(trend) == 3
    assert trend[0]["weight_lbs"] == 282.0
    assert trend[-1]["weight_lbs"] == 279.0


def test_get_latest_weight_returns_none_when_empty(isolated_db):
    assert isolated_db.get_latest_weight() is None


# --- Meals ---

def test_log_and_retrieve_meals(isolated_db):
    db = isolated_db
    db.log_meal("chicken breast and rice", estimated_calories=400, estimated_protein_g=40)
    meals = db.get_meals_today()
    assert len(meals) == 1
    assert meals[0]["description"] == "chicken breast and rice"
    assert meals[0]["estimated_calories"] == 400


def test_calories_today_sums_correctly(isolated_db):
    db = isolated_db
    db.log_meal("breakfast", estimated_calories=350)
    db.log_meal("lunch", estimated_calories=600)
    db.log_meal("snack", estimated_calories=150)
    assert db.get_calories_today() == 1100


def test_calories_today_zero_when_empty(isolated_db):
    assert isolated_db.get_calories_today() == 0


# --- Workouts ---

def test_log_and_retrieve_workout(isolated_db):
    db = isolated_db
    db.log_workout("elliptical", duration_minutes=45, calories_burned=380)
    last = db.get_last_workout()
    assert last is not None
    assert last["type"] == "elliptical"
    assert last["duration_minutes"] == 45
    assert last["calories_burned"] == 380


def test_workouts_this_week_count(isolated_db):
    db = isolated_db
    db.log_workout("elliptical", duration_minutes=40)
    db.log_workout("walk", duration_minutes=30)
    workouts = db.get_workouts_this_week()
    assert len(workouts) == 2


def test_last_workout_none_when_empty(isolated_db):
    assert isolated_db.get_last_workout() is None


# --- Apple Health ingestion ---

def test_ingest_apple_health_weight(isolated_db):
    db = isolated_db
    payload = {
        "data": {
            "metrics": [
                {
                    "name": "body_mass",
                    "units": "lb",
                    "data": [
                        {"date": "2026-04-05 08:00:00 -0400", "qty": 278.0}
                    ],
                }
            ],
            "workouts": [],
        }
    }
    result = db.ingest_apple_health(payload)
    assert result["weights"] == 1
    w = db.get_latest_weight()
    assert w["weight_lbs"] == 278.0
    assert w["source"] == "apple_health"


def test_ingest_apple_health_workout(isolated_db):
    db = isolated_db
    payload = {
        "data": {
            "metrics": [],
            "workouts": [
                {
                    "name": "Elliptical",
                    "start": "2026-04-05 07:00:00 -0400",
                    "end": "2026-04-05 07:45:00 -0400",
                    "duration": "45",
                    "activeEnergyBurned": {"qty": 380, "units": "kcal"},
                }
            ],
        }
    }
    result = db.ingest_apple_health(payload)
    assert result["workouts"] == 1
    last = db.get_last_workout()
    assert last["type"] == "Elliptical"
    assert last["duration_minutes"] == 45


def test_ingest_deduplicates_workouts(isolated_db):
    db = isolated_db
    payload = {
        "data": {
            "metrics": [],
            "workouts": [
                {
                    "name": "Elliptical",
                    "start": "2026-04-05 07:00:00 -0400",
                    "duration": "45",
                    "activeEnergyBurned": {"qty": 380, "units": "kcal"},
                }
            ],
        }
    }
    db.ingest_apple_health(payload)
    db.ingest_apple_health(payload)  # second call should not duplicate
    workouts = db.get_workouts_this_week()
    assert len(workouts) == 1


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


# --- Snapshot ---

def test_build_current_snapshot_no_data(isolated_db):
    snap = isolated_db.build_current_snapshot()
    assert "Wellbeing" in snap
    assert "not logged" in snap or "estimated" in snap


def test_build_current_snapshot_with_data(isolated_db):
    db = isolated_db
    db.log_weight(279.0)
    db.log_workout("elliptical", duration_minutes=40)
    db.log_meal("salad and chicken", estimated_calories=450)
    snap = db.build_current_snapshot()
    assert "279.0" in snap
    assert "elliptical" in snap
    assert "450" in snap
