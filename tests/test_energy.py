from __future__ import annotations

import pytest

from nutriologist.energy import daily_goal, mifflin_bmr


def test_mifflin_bmr_male():
    # 10·75 + 6.25·175 − 5·30 + 5 = 1698.75
    assert mifflin_bmr("М", 30, 175, 75) == pytest.approx(1698.75)


def test_mifflin_bmr_female():
    # 10·60 + 6.25·165 − 5·30 − 161 = 1320.25
    assert mifflin_bmr("Ж", 30, 165, 60) == pytest.approx(1320.25)


def test_daily_goal_male_maintenance():
    # BMR 1698.75 × 1.55 (средняя) × 1.0 (Поддержание) = 2633.06 → 2630
    g = daily_goal(
        sex="М", age=30, height=175, weight=75,
        activity="средняя", goal_type="Поддержание",
    )
    assert g["kcal"] == 2630
    assert g["protein"] == 135          # 75 × 1.8
    assert g["fat"] == 73               # 2630 × 0.25 / 9
    assert g["carbs"] == 358            # (2630 − 540 − 657) / 4
    # Macro energy reconstitutes close to the kcal target.
    energy = g["protein"] * 4 + g["fat"] * 9 + g["carbs"] * 4
    assert abs(energy - g["kcal"]) <= 5


def test_daily_goal_female_deficit():
    # BMR 1320.25 × 1.375 (низкая) × 0.85 (Похудение) = 1543 → 1540
    g = daily_goal(
        sex="Ж", age=30, height=165, weight=60,
        activity="низкая", goal_type="Похудение",
    )
    assert g["kcal"] == 1540
    assert g["protein"] == 108


def test_goal_type_ordering():
    kw = dict(sex="М", age=30, height=175, weight=75, activity="средняя")
    cut = daily_goal(goal_type="Похудение", **kw)["kcal"]
    keep = daily_goal(goal_type="Поддержание", **kw)["kcal"]
    gain = daily_goal(goal_type="Набор", **kw)["kcal"]
    assert cut < keep < gain


def test_underweight_deficit_is_blocked():
    # BMI = 45 / 1.7² ≈ 15.6 (underweight): «Похудение» must fall back to
    # maintenance, and a note explains it.
    cut = daily_goal(
        sex="Ж", age=30, height=170, weight=45,
        activity="средняя", goal_type="Похудение",
    )
    keep = daily_goal(
        sex="Ж", age=30, height=170, weight=45,
        activity="средняя", goal_type="Поддержание",
    )
    assert cut["kcal"] == keep["kcal"]
    assert cut["notes"] and any("18.5" in n for n in cut["notes"])


def test_obese_surplus_is_blocked():
    # BMI = 120 / 1.75² ≈ 39 (obese): «Набор» must fall back to maintenance.
    gain = daily_goal(
        sex="М", age=30, height=175, weight=120,
        activity="средняя", goal_type="Набор",
    )
    keep = daily_goal(
        sex="М", age=30, height=175, weight=120,
        activity="средняя", goal_type="Поддержание",
    )
    assert gain["kcal"] == keep["kcal"]
    assert gain["notes"]


def test_calorie_floor_enforced():
    # Small, older, sedentary → raw deficit would dip below the 1200 floor.
    g = daily_goal(
        sex="Ж", age=70, height=150, weight=42,
        activity="низкая", goal_type="Похудение",
    )
    assert g["kcal"] >= 1200
    assert any("минимум" in n for n in g["notes"])


def test_protein_never_dominates_energy():
    # Even at an extreme weight, protein stays within its energy-share cap.
    g = daily_goal(
        sex="М", age=30, height=180, weight=300,
        activity="средняя", goal_type="Поддержание",
    )
    assert g["protein"] * 4 <= 0.35 * g["kcal"] + 4  # +rounding slack


def test_normal_bmi_has_no_notes():
    g = daily_goal(
        sex="М", age=30, height=175, weight=75,
        activity="средняя", goal_type="Похудение",
    )
    assert g["notes"] == []


def test_unknown_activity_and_goal_fall_back_to_defaults():
    known = daily_goal(
        sex="М", age=30, height=175, weight=75,
        activity="средняя", goal_type="Поддержание",
    )
    unknown = daily_goal(
        sex="М", age=30, height=175, weight=75,
        activity="???", goal_type="???",
    )
    assert unknown["kcal"] == known["kcal"]
