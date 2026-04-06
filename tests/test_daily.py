"""Tests for wellbeing_mcp.daily — markdown-first data layer."""

from datetime import date, timedelta
from unittest.mock import patch

import pytest


@pytest.fixture(autouse=True)
def isolated_vault(tmp_path):
    """Redirect vault writes to a temp directory for each test."""
    import wellbeing_mcp.daily as daily_module

    daily_dir = tmp_path / "Well-being" / "Daily"
    daily_dir.mkdir(parents=True)

    with patch.object(daily_module, "DAILY_DIR", daily_dir):
        yield daily_module


TODAY = date.today()


# --- Weight ---


def test_log_weight_creates_note(isolated_vault):
    d = isolated_vault
    result = d.log_weight(279.5)
    assert "279.5" in result
    latest = d.get_latest_weight()
    assert latest is not None
    assert latest["weight_lbs"] == 279.5


def test_log_weight_shows_delta_to_goal(isolated_vault):
    result = isolated_vault.log_weight(280.0)
    assert "30.0" in result  # 280 - 250 = 30


def test_log_weight_for_past_date(isolated_vault):
    d = isolated_vault
    yesterday = TODAY - timedelta(days=1)
    d.log_weight(281.0, d=yesterday)
    latest = d.get_latest_weight()
    assert latest["weight_lbs"] == 281.0
    assert latest["date"] == str(yesterday)


def test_get_latest_weight_none_when_empty(isolated_vault):
    assert isolated_vault.get_latest_weight() is None


def test_weight_trend(isolated_vault):
    d = isolated_vault
    for i in range(5, 0, -1):
        day = TODAY - timedelta(days=i)
        d.log_weight(280.0 - i * 0.5, d=day)
    trend = d.get_weight_trend(days=7)
    assert len(trend) == 5
    # Should be in ascending date order
    assert trend[0]["date"] < trend[-1]["date"]


# --- Mood ---


def test_log_mood_score_and_energy(isolated_vault):
    d = isolated_vault
    result = d.log_mood(7, 6)
    assert "7/10" in result
    assert "6/10" in result
    latest = d.get_latest_mood()
    assert latest["score"] == 7
    assert latest["energy"] == 6


def test_log_mood_with_note(isolated_vault):
    result = isolated_vault.log_mood(8, None, note="feeling great")
    assert "feeling great" in result


def test_log_mood_partial(isolated_vault):
    d = isolated_vault
    d.log_mood(score=5, energy=None, note="")
    mood = d.get_latest_mood()
    assert mood["score"] == 5
    assert mood["energy"] is None


def test_get_latest_mood_none_when_empty(isolated_vault):
    assert isolated_vault.get_latest_mood() is None


# --- Meals ---


def test_log_meal_tracks_calories(isolated_vault):
    d = isolated_vault
    result = d.log_meal("grilled chicken and rice", 450, protein_g=40)
    assert "450" in result
    assert d.get_calories_today() == 450


def test_log_multiple_meals_sums_calories(isolated_vault):
    d = isolated_vault
    d.log_meal("breakfast", 350)
    d.log_meal("lunch", 600)
    d.log_meal("snack", 150)
    assert d.get_calories_today() == 1100


def test_calories_today_zero_when_empty(isolated_vault):
    assert isolated_vault.get_calories_today() == 0


def test_log_meal_shows_remaining(isolated_vault):
    result = isolated_vault.log_meal("lunch", 600)
    assert "remaining" in result


# --- Workout ---


def test_log_workout_to_daily(isolated_vault):
    d = isolated_vault
    d.log_workout_to_daily("A-push", duration_minutes=55)
    info = d.get_last_workout_info()
    assert info is not None
    assert info["workout_type"] == "A-push"
    assert info["workout_minutes"] == 55
    assert info["days_ago"] == 0


def test_get_workouts_this_week(isolated_vault):
    d = isolated_vault
    today = date.today()
    monday = today - timedelta(days=today.weekday())
    # Log workouts on Mon, Wed (if this week)
    for i in [0, 2]:
        day = monday + timedelta(days=i)
        if day <= today:
            d.log_workout_to_daily("cardio", d=day)
    workouts = d.get_workouts_this_week()
    assert len(workouts) >= 1


def test_get_last_workout_none_when_empty(isolated_vault):
    assert isolated_vault.get_last_workout_info() is None


# --- Snapshot ---


def test_build_current_snapshot_no_data(isolated_vault):
    profile = {"goal_weight_lbs": 250, "calorie_target": 2100}
    snap = isolated_vault.build_current_snapshot(profile)
    assert "Wellbeing" in snap
    assert "not logged" in snap or "nothing logged" in snap.lower() or "none" in snap.lower()


def test_build_current_snapshot_with_weight(isolated_vault):
    d = isolated_vault
    d.log_weight(279.0)
    profile = {"goal_weight_lbs": 250, "calorie_target": 2100, "current_weight_estimate_lbs": 280}
    snap = d.build_current_snapshot(profile)
    assert "279.0" in snap


# --- Personal notes preservation ---


def test_personal_notes_preserved_on_update(isolated_vault):
    d = isolated_vault
    # First log creates the note
    d.log_weight(280.0)

    # Manually append personal notes
    from wellbeing_mcp.daily import PERSONAL_NOTES_HEADER, _daily_path

    path = _daily_path(TODAY)
    existing = path.read_text()
    path.write_text(existing + f"\n{PERSONAL_NOTES_HEADER}\nRemember the gym bag.\n")

    # Log again — personal notes should survive
    d.log_weight(279.5)
    updated = path.read_text()
    assert "Remember the gym bag." in updated
