"""Tests for the calorie estimation helper in server.py"""

from wellbeing_mcp.server import _estimate_calories


def test_known_food_estimates():
    assert _estimate_calories("chicken breast") == 165
    assert _estimate_calories("protein shake") == 150
    assert _estimate_calories("salad") == 120


def test_combination_sums():
    est = _estimate_calories("chicken breast and rice")
    # chicken breast (165) + rice (200) = 365
    assert est == 365


def test_unknown_food_returns_default():
    # Unknown food → 400 default
    assert _estimate_calories("mystery meal") == 400


def test_result_is_capped():
    # Even a huge meal description shouldn't exceed 1500
    big = "pizza burger sandwich burrito steak pasta chips"
    assert _estimate_calories(big) <= 1500


def test_result_has_minimum():
    assert _estimate_calories("coffee") >= 50
