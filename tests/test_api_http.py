"""HTTP layer: routes, status codes and JSON shapes through FastAPI's TestClient.

The domain logic behind each endpoint has its own tests; this file checks the
wiring a frontend actually depends on. Every request goes through the real
`db_conn` dependency against a throwaway SQLite file, and the optional LLM is
forced off so nothing touches the network or `.env`.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import nutriologist.api.actions as actions_api
import nutriologist.api.planner as planner_api
import nutriologist.api.receipts_import as receipts_api
from nutriologist.api.app import create_app


@pytest.fixture
def client(tmp_path, monkeypatch) -> TestClient:
    monkeypatch.setenv("NUTRIOLOGIST_DB_PATH", str(tmp_path / "test.db"))
    for module in (actions_api, planner_api, receipts_api):
        monkeypatch.setattr(module, "get_optional_llm", lambda: None)
    return TestClient(create_app())


def _egg_meal(grams: float = 100) -> dict:
    return {
        "raw_text": "съел яйца",
        "title": "Завтрак",
        "items": [
            {
                "name": "яйцо куриное",
                "grams": grams,
                "unit": "г",
                "canonical_unit": "g",
                "category": "молочное",
                "per100": [157, 12.7, 11.5, 0.7],
            }
        ],
    }


def test_health(client) -> None:
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_empty_fridge_and_no_last_receipt(client) -> None:
    assert client.get("/api/inventory").json() == []
    assert client.get("/api/receipts/last").json() is None


def test_profile_defaults_then_roundtrip(client) -> None:
    profile = client.get("/api/profile").json()
    assert profile["goal"]["kcal"] > 0

    profile["goal"]["kcal"] = 1800
    profile["restrictions"] = ["без глютена"]
    assert client.put("/api/profile", json=profile).status_code == 200

    saved = client.get("/api/profile").json()
    assert saved["goal"]["kcal"] == 1800
    assert saved["restrictions"] == ["без глютена"]


def test_compute_goal_is_stateless_and_positive(client) -> None:
    r = client.post("/api/profile/compute-goal", json={})
    assert r.status_code == 200
    body = r.json()
    assert body["kcal"] > 1000
    assert isinstance(body["notes"], list)


def test_meal_lifecycle_create_diary_update_delete(client) -> None:
    created = client.post("/api/meals", json=_egg_meal(100))
    assert created.status_code == 200
    meal_id = created.json()["meal_id"]

    day = client.get("/api/diary/today").json()
    assert len(day["meals"]) == 1
    assert day["consumed"]["kcal"] == pytest.approx(157, abs=1)

    assert client.put(f"/api/meals/{meal_id}", json=_egg_meal(200)).status_code == 200
    assert client.get("/api/diary/today").json()["consumed"]["kcal"] == pytest.approx(314, abs=1)

    assert client.delete(f"/api/meals/{meal_id}").status_code == 204
    assert client.get("/api/diary/today").json()["meals"] == []


def test_update_unknown_meal_is_404(client) -> None:
    assert client.put("/api/meals/9999", json=_egg_meal()).status_code == 404


def test_inventory_add_then_trash(client) -> None:
    item = {
        "name": "гречка",
        "grams": 800,
        "canonical_unit": "g",
        "category": "крупы/макароны",
        "per100": [313, 12.6, 3.3, 62],
    }
    assert client.post("/api/inventory", json={"items": [item]}).json() == {"added": 1}

    fridge = client.get("/api/inventory").json()
    assert [i["name"] for i in fridge] == ["гречка"]

    pid = fridge[0]["product_id"]
    assert client.post(f"/api/inventory/{pid}/action", json={"action": "trash"}).json() == {"balance": 0}
    assert client.get("/api/inventory").json() == []


def test_inventory_action_errors(client) -> None:
    assert client.post("/api/inventory/9999/action", json={"action": "trash"}).status_code == 404

    client.post(
        "/api/inventory",
        json={"items": [{"name": "рис", "grams": 100, "canonical_unit": "g", "per100": [340, 7, 1, 76]}]},
    )
    pid = client.get("/api/inventory").json()[0]["product_id"]
    assert client.post(f"/api/inventory/{pid}/action", json={"action": "explode"}).status_code == 400


def test_chat_offline_understands_eating(client) -> None:
    r = client.post("/api/chat", json={"text": "съел 200 г гречки и два яйца"})
    assert r.status_code == 200
    body = r.json()
    assert body["intent"] == "eat"
    assert {i["name"] for i in body["items"]} >= {"гречка", "яйцо куриное"}


def test_chat_offline_understands_buying(client) -> None:
    r = client.post("/api/chat", json={"text": "купил кило абрикосов"})
    assert r.json()["intent"] == "buy"


def test_chat_gibberish_is_unknown_not_an_error(client) -> None:
    r = client.post("/api/chat", json={"text": "аыволдажыфвд"})
    assert r.status_code == 200
    assert r.json()["intent"] == "unknown"


def test_chat_report_intent_returns_diary(client) -> None:
    client.post("/api/meals", json=_egg_meal())
    r = client.post("/api/chat", json={"text": "отчёт за день"})
    assert r.json()["intent"] == "report"
    assert r.json()["report"]["consumed"]["kcal"] > 0


@pytest.mark.parametrize("days", [7, 30])
def test_stats_series_length_matches_window(client, days) -> None:
    body = client.get(f"/api/stats?days={days}").json()
    assert len(body["series"]) == days


@pytest.mark.parametrize("days", [0, 400])
def test_stats_rejects_out_of_range_window(client, days) -> None:
    assert client.get(f"/api/stats?days={days}").status_code == 422


def test_receipt_import_missing_file_is_404(client, tmp_path) -> None:
    r = client.post("/api/receipts/import", json={"path": str(tmp_path / "nope.pdf")})
    assert r.status_code == 404


def test_receipt_import_without_llm_is_422(client, tmp_path) -> None:
    pdf = tmp_path / "r.pdf"
    pdf.write_bytes(b"%PDF-1.4")
    r = client.post("/api/receipts/import", json={"path": str(pdf)})
    assert r.status_code == 422
    assert ".env" in r.json()["detail"]


def test_saved_recipes_start_empty(client) -> None:
    assert client.get("/api/recipes").json() == []
