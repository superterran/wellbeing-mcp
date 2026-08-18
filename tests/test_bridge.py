"""Tests for wellbeing_mcp.bridge — Health Auto Export webhook parsing.

Payload shapes here are copied from real HAE posts captured in apple_health_raw
on the closet deploy (Aug 2026), not invented — the bugs these cover were both
shape drift that the previous parser silently swallowed.
"""

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


def _parse(payload):
    from wellbeing_mcp.bridge import _parse_health_payload

    return _parse_health_payload(payload)


# --- Workouts ---


def test_workout_current_hae_shape_is_ingested(isolated_vault):
    """Current HAE sends name/start/end. This regressed to a silent no-op."""
    payload = {
        "data": {
            "workouts": [
                {
                    "id": "40467F61-C653-4FAA-8417-A398901ABF96",
                    "name": "Outdoor Cycling",
                    "location": "Outdoor",
                    "duration": 2528.584740638733,
                    "start": "2026-08-17 07:51:58 -0400",
                    "end": "2026-08-17 08:53:41 -0400",
                }
            ]
        }
    }
    ingested = _parse(payload)

    assert "workouts" in ingested, "workout was silently dropped"
    assert ingested["workouts"][0]["type"] == "outdoor cycling"
    assert ingested["workouts"][0]["duration_min"] == 42
    assert ingested["workouts"][0]["date"] == "2026-08-17"

    fm, _ = isolated_vault.read_daily(__import__("datetime").date(2026, 8, 17))
    assert fm["workout_type"] == "outdoor cycling"
    assert fm["workout_minutes"] == 42


def test_workout_legacy_shape_still_ingested(isolated_vault):
    """Older HAE sent workoutActivityType/startDate — keep accepting it."""
    payload = {
        "data": {
            "workouts": [
                {
                    "workoutActivityType": "HKWorkoutActivityTypeCycling",
                    "duration": 600,
                    "startDate": "2026-08-17 07:51:58 -0400",
                }
            ]
        }
    }
    ingested = _parse(payload)

    assert ingested["workouts"][0]["type"] == "cycling"
    assert ingested["workouts"][0]["duration_min"] == 10


# --- Activity rings ---


def test_ring_metrics_sum_per_day(isolated_vault):
    """Exercise minutes and stand hours arrive as many 1-unit points; they sum."""
    payload = {
        "data": {
            "metrics": [
                {
                    "name": "apple_exercise_time",
                    "units": "min",
                    "data": [
                        {"qty": 1, "date": "2026-08-17 07:52:00 -0400"},
                        {"qty": 1, "date": "2026-08-17 07:53:00 -0400"},
                        {"qty": 1, "date": "2026-08-17 07:54:00 -0400"},
                    ],
                },
                {
                    "name": "apple_stand_hour",
                    "units": "count",
                    "data": [
                        {"qty": 1, "date": "2026-08-17 07:00:00 -0400"},
                        {"qty": 1, "date": "2026-08-17 08:00:00 -0400"},
                    ],
                },
            ]
        }
    }
    _parse(payload)

    fm, _ = isolated_vault.read_daily(__import__("datetime").date(2026, 8, 17))
    assert fm["exercise_minutes"] == 3
    assert fm["stand_hours"] == 2


def test_cumulative_steps_sum_not_last_wins(isolated_vault):
    """Guards the existing per-day SUM behaviour for step_count."""
    payload = {
        "data": {
            "metrics": [
                {
                    "name": "step_count",
                    "units": "count",
                    "data": [
                        {"qty": 28.9, "date": "2026-08-17 06:34:00 -0400"},
                        {"qty": 21.1, "date": "2026-08-17 06:35:00 -0400"},
                    ],
                }
            ]
        }
    }
    _parse(payload)

    fm, _ = isolated_vault.read_daily(__import__("datetime").date(2026, 8, 17))
    assert fm["steps"] == 50
