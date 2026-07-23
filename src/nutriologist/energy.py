"""Daily calorie/macro goal from body metrics — Mifflin-St Jeor.

Pure domain logic (no FastAPI / DB imports) so it's trivially unit-tested and
reusable. The API layer (`api/profile.py`) wraps `daily_goal` into the `Macros`
response; the frontend recomputes the goal whenever the profile body changes.

Inputs mirror `api.profile.Body` + `goal_type`:
  sex        — «М» / «Ж» (anything not «Ж» is treated as male)
  activity   — «низкая» / «средняя» / «высокая»
  goal_type  — «Похудение» / «Поддержание» / «Набор»
"""

from __future__ import annotations

# TDEE = BMR × activity factor. Three-level scale matching the profile UI.
_ACTIVITY_FACTORS = {
    "низкая": 1.375,
    "средняя": 1.55,
    "высокая": 1.725,
}
_DEFAULT_ACTIVITY = 1.55

# Calorie target = TDEE × goal factor (deficit / maintenance / surplus).
_GOAL_FACTORS = {
    "Похудение": 0.85,
    "Поддержание": 1.0,
    "Набор": 1.1,
}
_DEFAULT_GOAL_FACTOR = 1.0

# Macro split: protein by body weight, fat as a share of energy, carbs the rest.
_PROTEIN_G_PER_KG = 1.8
_FAT_ENERGY_SHARE = 0.25
_KCAL_PER_G = {"protein": 4.0, "fat": 9.0, "carbs": 4.0}

# --- sanity guards (not medical advice — see the app's disclaimer) ----------
# The formula only estimates energy expenditure; it has no notion of whether a
# goal is healthy. These bounds stop obviously-unsafe targets: cutting while
# underweight, bulking while obese, a starvation-level floor, or an absurd
# protein number at extreme body weights.
_BMI_UNDERWEIGHT = 18.5      # below → block a deliberate deficit
_BMI_OBESE = 30.0            # at/above → block a deliberate surplus
_KCAL_FLOOR = {"Ж": 1200, "М": 1500}
_PROTEIN_MAX_ENERGY_SHARE = 0.35  # protein never exceeds this share of energy


def _bmi(height: int, weight: float) -> float:
    return weight / (height / 100.0) ** 2 if height else 0.0


def mifflin_bmr(sex: str, age: int, height: int, weight: float) -> float:
    """Basal metabolic rate (kcal/day), Mifflin-St Jeor.

    men:   10·weight + 6.25·height − 5·age + 5
    women: 10·weight + 6.25·height − 5·age − 161
    """
    base = 10.0 * weight + 6.25 * height - 5.0 * age
    return base - 161.0 if str(sex).strip().upper() == "Ж" else base + 5.0


def daily_goal(
    *, sex: str, age: int, height: int, weight: float, activity: str, goal_type: str
) -> dict:
    """Daily goal from body metrics, with sanity guards.

    Returns `{kcal, protein, fat, carbs, notes}` — kcal rounded to 10, grams to
    1, and `notes` a list of human-readable strings for any guard that fired
    (empty when the raw goal was already sane). See the guard constants above.
    """
    is_female = str(sex).strip().upper() == "Ж"
    bmi = _bmi(height, weight)
    notes: list[str] = []

    # 1. Don't let the *direction* of the goal be unsafe for the body.
    effective_goal = goal_type
    if goal_type == "Похудение" and 0 < bmi < _BMI_UNDERWEIGHT:
        effective_goal = "Поддержание"
        notes.append(
            "При недостатке массы (ИМТ < 18.5) дефицит не рекомендуется — "
            "цель рассчитана на поддержание."
        )
    elif goal_type == "Набор" and bmi >= _BMI_OBESE:
        effective_goal = "Поддержание"
        notes.append(
            "При высоком ИМТ (≥ 30) набор массы не рекомендуется — "
            "цель рассчитана на поддержание."
        )

    bmr = mifflin_bmr(sex, age, height, weight)
    tdee = bmr * _ACTIVITY_FACTORS.get(activity, _DEFAULT_ACTIVITY)
    kcal = tdee * _GOAL_FACTORS.get(effective_goal, _DEFAULT_GOAL_FACTOR)
    kcal = max(0, round(kcal / 10) * 10)

    # 2. Never recommend below a safe minimum.
    floor = _KCAL_FLOOR["Ж" if is_female else "М"]
    if 0 < kcal < floor:
        kcal = floor
        notes.append(f"Цель поднята до безопасного минимума {floor} ккал.")

    # 3. Protein by body weight, but capped so it can't dominate the energy
    #    budget at extreme weights (guards e.g. 300 кг → 540 г белка).
    protein_cap = _PROTEIN_MAX_ENERGY_SHARE * kcal / _KCAL_PER_G["protein"]
    protein = max(0, round(min(weight * _PROTEIN_G_PER_KG, protein_cap)))
    fat = max(0, round(kcal * _FAT_ENERGY_SHARE / _KCAL_PER_G["fat"]))
    carbs_kcal = kcal - protein * _KCAL_PER_G["protein"] - fat * _KCAL_PER_G["fat"]
    carbs = max(0, round(carbs_kcal / _KCAL_PER_G["carbs"]))

    return {"kcal": kcal, "protein": protein, "fat": fat, "carbs": carbs, "notes": notes}
