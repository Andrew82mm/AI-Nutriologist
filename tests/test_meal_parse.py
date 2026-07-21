"""Phase A: LLM fallback for chat food parsing (intent + items)."""

from __future__ import annotations

import nutriologist.api.actions as actions
from nutriologist.db import get_connection
from nutriologist.products.meal_parse import parse_meal_text

from product_fakes import RoutingFakeLLM, meal_response, nutrition_response


# --- unit: parse_meal_text -------------------------------------------------
def test_parse_meal_text_returns_intent_and_items() -> None:
    llm = RoutingFakeLLM(
        meal=meal_response(
            intent="eat",
            items=[
                {"name": "плов", "amount": 300, "unit": "g", "category": "блюда"},
                {"name": "шаурма", "amount": 250, "unit": "g", "category": "блюда"},
            ],
        )
    )

    res = parse_meal_text("съел плов 300 г и шаурму", llm)

    assert res.intent == "eat"
    assert [i.name for i in res.items] == ["плов", "шаурма"]
    assert res.items[0].amount == 300
    assert res.items[0].unit == "g"


def test_parse_meal_text_skips_blank_names_and_coerces() -> None:
    llm = RoutingFakeLLM(
        meal={
            "intent": "buy",
            "items": [
                {"name": "  ", "amount": 1, "unit": "g", "category": "прочее"},
                {"name": "фейхоа", "amount": None, "unit": "bogus", "category": "чужое"},
            ],
        }
    )

    res = parse_meal_text("купил фейхоа", llm)

    assert res.intent == "buy"
    assert len(res.items) == 1
    assert res.items[0].name == "фейхоа"
    assert res.items[0].unit == "g"        # unknown unit → g
    assert res.items[0].category is None   # unknown category → None


# --- integration: the chat endpoint hybrid ---------------------------------
def _chat(conn, text: str) -> dict:
    return actions.chat(actions.ChatIn(text=text), conn)


def test_chat_llm_fallback_for_unknown_eaten_food(monkeypatch) -> None:
    conn = get_connection(":memory:")
    llm = RoutingFakeLLM(
        meal=meal_response(
            intent="eat",
            items=[
                {"name": "плов", "amount": 300, "unit": "g", "category": "блюда"},
                {"name": "шаурма", "amount": 250, "unit": "g", "category": "блюда"},
            ],
        ),
        nutrition=nutrition_response(),
    )
    monkeypatch.setattr(actions, "get_optional_llm", lambda: llm)

    resp = _chat(conn, "съел плов 300 г и шаурму")

    assert resp["intent"] == "eat"
    assert [i["name"] for i in resp["items"]] == ["плов", "шаурма"]
    assert "total" in resp


def test_chat_llm_fallback_keeps_buy_intent_from_verb(monkeypatch) -> None:
    conn = get_connection(":memory:")
    # LLM guesses 'eat', but the verb «купил» is explicit — the rule wins.
    llm = RoutingFakeLLM(
        meal=meal_response(intent="eat", items=[{"name": "пельмени", "amount": 400, "unit": "g"}]),
        nutrition=nutrition_response(),
    )
    monkeypatch.setattr(actions, "get_optional_llm", lambda: llm)

    resp = _chat(conn, "купил пельмени")

    assert resp["intent"] == "buy"
    assert resp["items"][0]["name"] == "пельмени"


def test_chat_uses_llm_intent_when_rule_is_unknown(monkeypatch) -> None:
    conn = get_connection(":memory:")
    # No verb the rule recognizes → rule intent 'unknown'; trust the LLM's 'eat'.
    llm = RoutingFakeLLM(
        meal=meal_response(intent="eat", items=[{"name": "бургер", "amount": 1, "unit": "piece"}]),
        nutrition=nutrition_response(),
    )
    monkeypatch.setattr(actions, "get_optional_llm", lambda: llm)

    resp = _chat(conn, "на завтрак бургер")

    assert resp["intent"] == "eat"
    assert resp["items"][0]["name"] == "бургер"


def test_chat_llm_primary_parses_mixed_phrase(monkeypatch) -> None:
    """LLM-primary: a phrase mixing a staple (творог) with unknown foods returns
    ALL positions — the exact case the rules-first gate used to drop."""
    conn = get_connection(":memory:")
    llm = RoutingFakeLLM(
        meal=meal_response(
            intent="eat",
            items=[
                {"name": "творог обезжиренный", "amount": 150},
                {"name": "йогурт греческий 2%", "amount": 125},
                {"name": "хлеб", "amount": 32},
                {"name": "сыр", "amount": 37},
                {"name": "нектарин", "amount": 120},
            ],
        ),
        nutrition=nutrition_response(),
    )
    monkeypatch.setattr(actions, "get_optional_llm", lambda: llm)

    resp = _chat(conn, "на завтрак 150г творог обезжиренный 125г йогурт греческий 2% 32г хлеба 37г сыр 120г нектарины")

    assert resp["intent"] == "eat"
    assert [i["name"] for i in resp["items"]] == [
        "творог обезжиренный", "йогурт греческий 2%", "хлеб", "сыр", "нектарин",
    ]


def test_chat_offline_rules_fallback_when_no_llm(monkeypatch) -> None:
    """Without an LLM, the deterministic rule table still handles staples."""
    conn = get_connection(":memory:")
    monkeypatch.setattr(actions, "get_optional_llm", lambda: None)

    resp = _chat(conn, "съел творог 5% 200 г")

    assert resp["intent"] == "eat"
    assert any("творог" in i["name"] for i in resp["items"])


def test_chat_unknown_without_llm(monkeypatch) -> None:
    conn = get_connection(":memory:")
    monkeypatch.setattr(actions, "get_optional_llm", lambda: None)

    resp = _chat(conn, "съел плов 300 г")

    assert resp["intent"] == "unknown"


# --- point C: inline macros from the phrase win, tagged as 'user' -----------
def test_chat_honors_inline_macros(monkeypatch) -> None:
    conn = get_connection(":memory:")
    llm = RoutingFakeLLM(
        meal=meal_response(intent="eat", items=[
            {"name": "хлеб", "amount": 32, "protein_100": 8.5, "fat_100": 2.5, "carbs_100": 54},
        ]),
        nutrition=nutrition_response(),  # would be used only if no user macros
    )
    monkeypatch.setattr(actions, "get_optional_llm", lambda: llm)

    resp = _chat(conn, "съел 32г хлеба с бжу 8,5 2,5 54")

    it = resp["items"][0]
    # per100 = [kcal, protein, fat, carbs]; kcal = 8.5*4 + 2.5*9 + 54*4 = 272.5
    assert it["per100"] == [272.5, 8.5, 2.5, 54]
    assert it["per100_source"] == "user"
    # portion (32 g) macros are the per-100 scaled by 0.32
    assert it["kcal"] == round(272.5 * 0.32)
    assert it["protein"] == round(8.5 * 0.32, 1)


def test_parse_meal_text_reads_inline_macros() -> None:
    llm = RoutingFakeLLM(meal=meal_response(intent="eat", items=[
        {"name": "сыр", "amount": 37, "protein_100": 31.2, "fat_100": 18.2},
    ]))
    res = parse_meal_text("съел 37г сыр с бжу 31,2 18,2", llm)
    it = res.items[0]
    assert it.user_macros == (31.2, 18.2, 0.0)  # carbs defaulted to 0


# --- point B: qualified variants aren't coerced onto a coarse staple --------
def test_estimate_position_respects_qualified_variant() -> None:
    conn = get_connection(":memory:")
    # Exact staple name → trusts the staple's 5% macros (no LLM needed).
    full = actions.estimate_position(conn, "творог 5%", None, None)
    assert full["per100"][0] == 121  # творог 5% staple kcal

    # A qualified variant must resolve through the cascade, not the 5% staple.
    llm = RoutingFakeLLM(nutrition=nutrition_response(kcal=71, protein=18, fat=0.1, carbs=3.3))
    lean = actions.estimate_position(conn, "творог обезжиренный", None, llm)
    assert lean["known"] is True
    assert lean["per100"] != full["per100"]
    assert lean["per100"][0] != 121
