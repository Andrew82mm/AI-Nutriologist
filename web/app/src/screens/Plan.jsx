// Plan (План) — generates a day's menu + shopping list from goals and inventory
// via POST /api/plan/day. БЖУ shown is the backend's deterministic recompute
// (not the LLM's arithmetic). Needs an LLM configured in .env — a 422 surfaces
// as a hint. Generation is on demand (it costs an LLM call), not on mount.

import { useState } from "react";
import { api } from "../api";

const UNIT = { g: "г", ml: "мл", piece: "шт" };
const fmtG = (g) => `${Math.round(g)} г`;

export default function Plan() {
  const [plan, setPlan] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  const generate = async () => {
    setBusy(true);
    setError(null);
    try {
      setPlan(await api.planDay());
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div>
      <button className="btn btn-primary btn-block" onClick={generate} disabled={busy}>
        {busy ? "Составляю…" : plan ? "Пересоставить план" : "Составить план на день"}
      </button>

      {error && <div className="state-msg" style={{ marginTop: 12 }}>Не удалось: {error}</div>}

      {plan && (
        <>
          <div className="note" style={{ marginTop: 12 }}>
            Итого: {plan.totals.kcal} / {plan.goal.kcal} ккал · Б {plan.totals.protein} · Ж{" "}
            {plan.totals.fat} · У {plan.totals.carbs}
            {plan.adjusted ? " · план скорректирован под цель" : ""}
          </div>

          {plan.meals.map((m, i) => (
            <div className="meal-card" key={i}>
              <div className="meal-head">
                <span className="meal-title">{m.title}</span>
                <span className="meal-kcal">
                  {Math.round(m.items.reduce((s, it) => s + (it.kcal || 0), 0))} ккал
                </span>
              </div>
              <div className="meal-items">
                {m.items
                  .map((it) => `${it.name} ${it.grams}${UNIT.g}${it.known ? "" : " (≈)"}`)
                  .join(" · ")}
              </div>
            </div>
          ))}

          <div className="cat-line" style={{ marginTop: 16 }}>
            <span className="cat-name">Купить</span>
            <span className="cat-rule" />
            <span className="cat-count">{plan.shopping_list.length} поз.</span>
          </div>
          {plan.shopping_list.length === 0 ? (
            <div className="state-msg">Всё нужное уже есть дома.</div>
          ) : (
            plan.shopping_list.map((s, i) => (
              <div className="card elev-sm product-card" key={i}>
                <div className="product-head">
                  <span className="product-name">{s.name}</span>
                  <span className="product-amount">{fmtG(s.grams)}</span>
                </div>
              </div>
            ))
          )}
        </>
      )}
    </div>
  );
}
