import { useEffect, useState } from "react";
import { api } from "../api";
import { IconChevronRight } from "../Icons";
import MealForm from "../MealForm";

const MACROS = [
  ["Б", "protein", "var(--mc-b)"],
  ["Ж", "fat", "var(--mc-zh)"],
  ["У", "carbs", "var(--mc-u)"],
];

const SRC_CLASS = { "база": "tag-neutral", "введено": "tag-accent", "≈ оценка": "tag-outline" };
const UNIT_LABEL = { g: "г", ml: "мл", piece: "шт" };
const RING_C = 351.85; // circumference of the r=56 progress ring

const pct = (c, g) => Math.max(0, Math.min(100, (c / (g || 1)) * 100));

// A fridge item is "running low" below these thresholds in its canonical unit.
function isLow(item) {
  return item.unit === "piece" ? item.amount < 3 : item.amount < 250;
}

function MacroBars({ consumed, goal }) {
  return (
    <div className="macro-bars">
      {MACROS.map(([label, key, color]) => (
        <div className="macro-row" key={key}>
          <span className="macro-badge" style={{ background: color }}>{label}</span>
          <span className="macro-track">
            <span className="macro-fill" style={{ width: pct(consumed[key], goal[key]) + "%", background: color }} />
          </span>
          <span className="macro-val">
            <b>{Math.round(consumed[key])}</b>
            <span style={{ opacity: 0.5 }}> / {Math.round(goal[key])} г</span>
          </span>
        </div>
      ))}
    </div>
  );
}

function Ring({ consumed, goal, remaining }) {
  const offset = RING_C * (1 - Math.min(consumed / (goal || 1), 1));
  return (
    <div className="ring-wrap">
      <svg width="132" height="132" viewBox="0 0 132 132" style={{ transform: "rotate(-90deg)" }}>
        <circle cx="66" cy="66" r="56" fill="none" stroke="var(--color-divider)" strokeWidth="12" />
        <circle
          cx="66" cy="66" r="56" fill="none" stroke="var(--color-accent)" strokeWidth="12"
          strokeLinecap="round" strokeDasharray={RING_C} strokeDashoffset={offset}
          style={{ transition: "stroke-dashoffset .5s ease" }}
        />
      </svg>
      <div className="ring-center">
        <div className="ring-kcal">{remaining}</div>
        <div className="ring-sub">осталось ккал</div>
      </div>
    </div>
  );
}

function MealCard({ meal, onEdit }) {
  return (
    <button className="card elev-sm meal-card" onClick={onEdit}>
      <div className="meal-head">
        <span className="meal-title">{meal.title}</span>
        <span className="meal-time">{meal.ts.slice(11, 16)}</span>
        <span className="meal-kcal">{Math.round(meal.macros.kcal)} ккал</span>
        <span className="meal-chevron"><IconChevronRight /></span>
      </div>
      <div className="meal-items">{meal.items.map((i) => i.name).join(" · ") || "—"}</div>
      <div className="meal-macros">
        {MACROS.map(([label, key, color]) => (
          <span className="macro-chip" key={key}>
            <span className="macro-dot" style={{ background: color }} />
            {label} {Math.round(meal.macros[key])}
          </span>
        ))}
        <span className={"tag " + (SRC_CLASS[meal.source] || "tag-neutral")} style={{ marginLeft: "auto" }}>
          {meal.source}
        </span>
      </div>
    </button>
  );
}

function HomeBlock({ items, onOpenFridge }) {
  const low = items.filter(isLow).map((i) => i.name);
  return (
    <div className="card elev-sm home-card">
      <div className="home-head">
        <span className="section-head" style={{ margin: 0 }}>Дома есть</span>
        <button className="btn btn-ghost" style={{ fontSize: 13 }} onClick={onOpenFridge}>
          Весь холодильник →
        </button>
      </div>
      <div className="home-list">
        {items.slice(0, 4).map((it) => (
          <div className="home-item" key={it.product_id}>
            <span className="home-dot" />
            <span className="home-name">{it.name}</span>
            <span className="home-amount">
              {Math.round(it.amount)} {UNIT_LABEL[it.unit] || it.unit}
            </span>
            {isLow(it) && <span className="tag tag-neutral" style={{ fontSize: 10 }}>докупить</span>}
          </div>
        ))}
      </div>
      {low.length > 0 && (
        <div className="home-note">
          {low.join(" и ")} {low.length > 1 ? "заканчиваются" : "заканчивается"} — добавьте в список покупок на вкладке «План».
        </div>
      )}
    </div>
  );
}

export default function Diary({ reloadKey, onOpenChat, onOpenFridge, onChanged }) {
  const [tab, setTab] = useState("today");
  const [day, setDay] = useState(null);
  const [inventory, setInventory] = useState([]);
  const [error, setError] = useState(null);
  const [form, setForm] = useState(null); // null | {mode:'add'} | {mode:'edit', meal}

  useEffect(() => {
    setError(null);
    api.getDiary().then(setDay).catch((e) => setError(e.message));
    api.getInventory().then(setInventory).catch(() => {});
  }, [reloadKey]);

  const afterChange = () => {
    setForm(null);
    onChanged?.(); // bump parent reloadKey → refetch diary + inventory
  };

  const saveMeal = async (items) => {
    if (form?.mode === "edit") await api.updateMeal(form.meal.id, items);
    else await api.addManualMeal(items);
    afterChange();
  };
  const deleteMeal = async () => {
    if (form?.mode === "edit") await api.deleteMeal(form.meal.id);
    afterChange();
  };

  return (
    <div className="diary">
      <div className="seg" style={{ display: "flex" }}>
        <label className="seg-opt" style={{ flex: 1, justifyContent: "center" }}>
          <input type="radio" name="diarytab" checked={tab === "today"} onChange={() => setTab("today")} />
          Сегодня
        </label>
        <label className="seg-opt" style={{ flex: 1, justifyContent: "center" }}>
          <input type="radio" name="diarytab" checked={tab === "stats"} onChange={() => setTab("stats")} />
          Статистика
        </label>
      </div>

      {tab === "stats" ? (
        <div className="state-msg">Статистика — скоро.</div>
      ) : error ? (
        <div className="state-msg">Ошибка загрузки: {error}</div>
      ) : day === null ? (
        <div className="state-msg">Загрузка…</div>
      ) : (
        <>
          <div className="card elev-sm ring-card">
            <div className="ring-top">
              <Ring consumed={day.consumed.kcal} goal={day.goal.kcal} remaining={day.remaining_kcal} />
              <div className="ring-side">
                <div className="ring-line">
                  <span className="ring-label">Съедено</span>
                  <span className="ring-eaten">{Math.round(day.consumed.kcal)}</span>
                </div>
                <div className="ring-div" />
                <div className="ring-line">
                  <span className="ring-label">Цель</span>
                  <span className="ring-goal">{Math.round(day.goal.kcal)} ккал</span>
                </div>
              </div>
            </div>
            <MacroBars consumed={day.consumed} goal={day.goal} />
          </div>

          <div className="meals-head">
            <span className="section-head" style={{ margin: 0 }}>Приёмы пищи</span>
            <span className="meals-date">сегодня</span>
          </div>

          {day.meals.length === 0 ? (
            <div className="card empty-card">
              <div className="empty-title">Ещё нет данных</div>
              <div className="empty-sub">Напишите в строке ниже, что съели или купили — например «съел тарелку борща».</div>
              <button className="btn btn-primary" style={{ marginTop: 6 }} onClick={onOpenChat}>
                Записать первый приём
              </button>
            </div>
          ) : (
            day.meals.map((m) =>
              form?.mode === "edit" && form.meal.id === m.id ? (
                <MealForm
                  key={m.id}
                  mode="edit"
                  initialItems={m.items}
                  onSave={saveMeal}
                  onDelete={deleteMeal}
                  onCancel={() => setForm(null)}
                />
              ) : (
                <MealCard key={m.id} meal={m} onEdit={() => setForm({ mode: "edit", meal: m })} />
              )
            )
          )}

          {/* add form / button */}
          {form?.mode === "add" ? (
            <MealForm mode="add" onSave={saveMeal} onCancel={() => setForm(null)} />
          ) : (
            <button
              className="btn btn-secondary btn-block"
              style={{ gap: 8, borderStyle: "dashed" }}
              onClick={() => setForm({ mode: "add" })}
            >
              + Добавить приём пищи
            </button>
          )}

          {inventory.length > 0 && <HomeBlock items={inventory} onOpenFridge={onOpenFridge} />}

          <p className="diary-footnote">Информация справочная, не медицинская рекомендация.</p>
        </>
      )}
    </div>
  );
}
