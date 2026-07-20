import { useEffect, useState } from "react";
import { api } from "../api";

const MACROS = [
  ["Б", "protein", "var(--mc-b)"],
  ["Ж", "fat", "var(--mc-zh)"],
  ["У", "carbs", "var(--mc-u)"],
];

function MacroBars({ consumed, goal }) {
  return (
    <div>
      {MACROS.map(([label, key, color]) => {
        const c = consumed[key] || 0;
        const g = goal[key] || 1;
        const pct = Math.max(0, Math.min(100, (c / g) * 100));
        return (
          <div className="macro-row" key={key}>
            <span className="macro-label" style={{ color }}>{label}</span>
            <span className="macro-track">
              <span className="macro-fill" style={{ width: pct + "%", background: color }} />
            </span>
            <span className="macro-val">{Math.round(c)} / {Math.round(g)} г</span>
          </div>
        );
      })}
    </div>
  );
}

export default function Diary({ reloadKey }) {
  const [day, setDay] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    setError(null);
    api.getDiary().then(setDay).catch((e) => setError(e.message));
  }, [reloadKey]);

  if (error) return <div className="state-msg">Ошибка загрузки: {error}</div>;
  if (day === null) return <div className="state-msg">Загрузка…</div>;

  const kcalPct = Math.min(100, (day.consumed.kcal / (day.goal.kcal || 1)) * 100);

  return (
    <div>
      <div className="summary-card">
        <div className="summary-top">
          <span className="summary-kcal">{Math.round(day.consumed.kcal)}</span>
          <span className="summary-goal">/ {Math.round(day.goal.kcal)} ккал</span>
        </div>
        <div className="summary-remaining">Осталось {day.remaining_kcal} ккал</div>
        <div className="macro-track" style={{ marginBottom: 4 }}>
          <span className="macro-fill" style={{ width: kcalPct + "%", background: "var(--color-accent)" }} />
        </div>
        <MacroBars consumed={day.consumed} goal={day.goal} />
      </div>

      {day.meals.length === 0 ? (
        <div className="state-msg">Сегодня пока ничего не записано. Откройте чат и напишите, что съели.</div>
      ) : (
        day.meals.map((m) => (
          <div className="meal-card" key={m.id}>
            <div className="meal-head">
              <span className="meal-title">{m.title}</span>
              <span className="meal-time">{m.ts.slice(11, 16)}</span>
              <span className="meal-kcal">{Math.round(m.macros.kcal)} ккал</span>
            </div>
            <div className="meal-items">{m.items.map((i) => i.name).join(" · ") || "—"}</div>
          </div>
        ))
      )}
    </div>
  );
}
