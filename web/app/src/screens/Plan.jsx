// Plan (План) — two views behind a toggle at the top:
//   • «План на день» — a day of recipes + a shopping list, from goals and
//     inventory via POST /api/plan/day. БЖУ is the backend's deterministic
//     recompute (not the LLM's math). «Приготовить» cooks a recipe through the
//     shared cook flow (consumes ingredients, stocks the dish, saves the recipe).
//   • «Мои рецепты» — the saved-recipe library (GET /api/recipes): every dish
//     ever cooked, with ingredients, steps and БЖУ. Cook again or delete.
// Plan generation needs an LLM in .env — a 422 surfaces as a hint.

import { useEffect, useState } from "react";
import { api } from "../api";
import { IconChevronRight, IconTrash } from "../Icons";

const round = (x) => Math.round(x || 0);
const catLabel = (c) => (c || "прочее").toUpperCase();

// A little frying pan, for the «Приготовить» button.
const IconPan = () => (
  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor"
    strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <circle cx="10" cy="13" r="7" />
    <path d="M17 13h5" />
  </svg>
);

// Collapsible cooking steps — shared by planned and saved recipe cards.
function RecipeSteps({ steps }) {
  const [open, setOpen] = useState(false);
  if (!steps || steps.length === 0) return null;
  return (
    <div>
      <button className={"recipe-toggle" + (open ? " is-open" : "")} onClick={() => setOpen((o) => !o)}>
        <IconChevronRight size={12} />
        {open ? "Скрыть рецепт" : "Показать рецепт"}
      </button>
      {open && (
        <ol className="recipe-steps">
          {steps.map((s, i) => <li key={i}>{s}</li>)}
        </ol>
      )}
    </div>
  );
}

// The «Приготовить / Готовлю… / Приготовлено ✓» button (shared).
function CookButton({ status, onClick }) {
  return (
    <button
      className={"btn btn-block btn-cook" + (status === "done" ? " is-done" : "")}
      style={{ marginTop: 10 }}
      disabled={status === "busy" || status === "done"}
      onClick={onClick}
    >
      {status === "done" ? "Приготовлено ✓" : status === "busy" ? "Готовлю…" : (<><IconPan /> Приготовить</>)}
    </button>
  );
}

function MealTag({ have }) {
  return (
    <span className={"tag " + (have ? "tag-accent-2" : "tag-neutral")}>
      {have ? "есть дома" : "докупить"}
    </span>
  );
}

function RecipeCard({ meal, have, status, onCook }) {
  const kcal = round(meal.items.reduce((s, it) => s + (it.kcal || 0), 0));
  const p = round(meal.items.reduce((s, it) => s + (it.protein || 0), 0));
  const f = round(meal.items.reduce((s, it) => s + (it.fat || 0), 0));
  const c = round(meal.items.reduce((s, it) => s + (it.carbs || 0), 0));
  const dish = meal.dish || meal.items.map((it) => it.name).join(" · ") || "Блюдо";
  const ingredients = meal.items.map((it) => `${it.name} ${round(it.grams)} г`).join(" · ");

  return (
    <div className="card elev-sm meal-card" style={{ marginTop: 12 }}>
      <div className="meal-head">
        <span
          className="meal-title"
          style={{ flex: 1, fontSize: 12, letterSpacing: 0.5, textTransform: "uppercase", color: "var(--color-accent-700)" }}
        >
          {meal.title}
        </span>
        <span className="meal-kcal">{kcal} ккал</span>
      </div>

      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <span style={{ fontWeight: 600, fontSize: 16, flex: 1 }}>{dish}</span>
        {meal.saved && <span className="tag tag-accent">из базы</span>}
      </div>

      <div className="meal-items">{ingredients || "—"}</div>

      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <span className="meal-items" style={{ flex: 1 }}>Б {p} · Ж {f} · У {c}</span>
        <MealTag have={have} />
      </div>

      <RecipeSteps steps={meal.steps} />
      <CookButton status={status} onClick={() => onCook(meal)} />
    </div>
  );
}

function SavedRecipeCard({ recipe, status, onCook, onDelete }) {
  const ingredients = recipe.ingredients.map((i) => `${i.name} ${round(i.grams)} г`).join(" · ");
  const totalKcal = round((recipe.kcal || 0) * (recipe.yield_grams || 0) / 100);

  return (
    <div className="card elev-sm meal-card" style={{ marginTop: 12 }}>
      <div className="meal-head" style={{ alignItems: "center" }}>
        <span style={{ fontWeight: 600, fontSize: 16, flex: 1 }}>{recipe.name}</span>
        {recipe.kcal > 0 && <span className="meal-kcal">{round(recipe.kcal)} ккал/100 г</span>}
        <button
          className="product-trash"
          style={{ marginLeft: 6 }}
          title="Удалить рецепт"
          onClick={() => onDelete(recipe)}
        >
          <IconTrash size={17} />
        </button>
      </div>

      <div className="meal-items">{ingredients || "—"}</div>

      <div className="meal-items">
        {recipe.kcal > 0
          ? `Б ${round(recipe.protein)} · Ж ${round(recipe.fat)} · У ${round(recipe.carbs)} · всё блюдо ≈ ${totalKcal} ккал (${round(recipe.yield_grams)} г)`
          : "БЖУ не рассчитан"}
      </div>

      <RecipeSteps steps={recipe.steps} />
      <CookButton status={status} onClick={() => onCook(recipe)} />
    </div>
  );
}

// ── «Мои рецепты» view ──────────────────────────────────────────────────────
function MyRecipes() {
  const [recipes, setRecipes] = useState(null);
  const [error, setError] = useState(null);
  const [cookState, setCookState] = useState({}); // recipe id -> 'busy' | 'done'

  const load = async () => {
    setError(null);
    try {
      setRecipes(await api.getRecipes());
    } catch (e) {
      setError(e.message);
    }
  };

  useEffect(() => { load(); }, []);

  const cook = async (recipe) => {
    setCookState((s) => ({ ...s, [recipe.id]: "busy" }));
    try {
      await api.cookFromChat(
        recipe.name,
        recipe.ingredients.map((i) => ({ name: i.name, grams: i.grams })),
        recipe.yield_grams,
        recipe.steps,
      );
      setCookState((s) => ({ ...s, [recipe.id]: "done" }));
    } catch (e) {
      setCookState((s) => ({ ...s, [recipe.id]: undefined }));
      setError("Не удалось приготовить: " + e.message);
    }
  };

  const remove = async (recipe) => {
    if (!window.confirm(`Удалить рецепт «${recipe.name}»? Приготовленное блюдо и его остатки останутся.`)) return;
    try {
      await api.deleteRecipe(recipe.id);
      setRecipes((rs) => rs.filter((r) => r.id !== recipe.id));
    } catch (e) {
      setError(e.message);
    }
  };

  if (recipes === null && !error) return <div className="state-msg">Загрузка…</div>;

  return (
    <div>
      {error && <div className="state-msg" style={{ marginTop: 4 }}>Не удалось: {error}</div>}
      {recipes && recipes.length === 0 ? (
        <div className="card empty-card" style={{ marginTop: 12 }}>
          <div className="empty-title">Пока нет рецептов</div>
          <div className="empty-sub">
            Приготовьте блюдо — на экране «План», в холодильнике или через чат
            («приготовил омлет из …»), — и оно сохранится сюда.
          </div>
        </div>
      ) : (
        (recipes || []).map((r) => (
          <SavedRecipeCard
            key={r.id}
            recipe={r}
            status={cookState[r.id]}
            onCook={cook}
            onDelete={remove}
          />
        ))
      )}
    </div>
  );
}

// ── «План на день» view ─────────────────────────────────────────────────────
function DayPlanView() {
  const [plan, setPlan] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [ticked, setTicked] = useState({}); // local "picked up while shopping" state
  const [cookState, setCookState] = useState({}); // meal index -> 'busy' | 'done'
  const [copied, setCopied] = useState(false);

  const generate = async () => {
    setBusy(true);
    setError(null);
    try {
      setPlan(await api.planDay());
      setTicked({});
      setCookState({});
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };

  // A meal is "есть дома" when none of its ingredients are on the to-buy list.
  const toBuy = new Set((plan?.shopping_list || []).filter((s) => !s.have).map((s) => s.name));
  const mealHave = (m) => m.items.every((it) => !toBuy.has(it.name));

  const cookMeal = async (idx, meal) => {
    setCookState((s) => ({ ...s, [idx]: "busy" }));
    try {
      await api.cookFromChat(
        meal.dish || meal.title,
        meal.items.map((it) => ({ name: it.name, grams: it.grams })),
        null,
        meal.steps,
      );
      setCookState((s) => ({ ...s, [idx]: "done" }));
    } catch (e) {
      setCookState((s) => ({ ...s, [idx]: undefined }));
      setError("Не удалось приготовить: " + e.message);
    }
  };

  const copyList = async () => {
    const lines = (plan?.shopping_list || [])
      .filter((s) => !s.have)
      .map((s) => `• ${s.name} — ${s.amount} ${s.unit}`);
    const text = "Список покупок:\n" + (lines.join("\n") || "всё нужное уже есть дома");
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      /* clipboard blocked — ignore */
    }
  };

  // Group the shopping list by category, preserving the backend's order.
  const groups = [];
  for (const s of plan?.shopping_list || []) {
    const cat = s.category || "прочее";
    let g = groups[groups.length - 1];
    if (!g || g.cat !== cat) {
      g = { cat, items: [] };
      groups.push(g);
    }
    g.items.push(s);
  }

  return (
    <div>
      <button className="btn btn-primary btn-block" onClick={generate} disabled={busy}>
        {busy ? "Составляю…" : plan ? "Пересоставить план" : "Составить план на день"}
      </button>

      {error && <div className="state-msg" style={{ marginTop: 12 }}>Не удалось: {error}</div>}

      {plan && (
        <>
          <div className="card elev-sm" style={{ padding: 14, marginTop: 12 }}>
            <div style={{ display: "flex", alignItems: "baseline" }}>
              <span style={{ flex: 1, fontWeight: 600 }}>Итого за день</span>
              <span style={{ fontFamily: "var(--font-heading)", fontSize: 22, fontWeight: 700 }}>
                {plan.totals.kcal}
              </span>
              <span style={{ opacity: 0.55, marginLeft: 4 }}>/ {plan.goal.kcal} ккал</span>
            </div>
            <div style={{ height: 10, borderRadius: 6, background: "var(--color-divider)", overflow: "hidden", margin: "10px 0 8px" }}>
              <div
                style={{
                  height: "100%",
                  width: Math.min(100, plan.goal.kcal ? (plan.totals.kcal / plan.goal.kcal) * 100 : 0) + "%",
                  background: "var(--color-accent)",
                  borderRadius: 6,
                }}
              />
            </div>
            <div style={{ fontSize: 13, opacity: 0.7 }}>
              Б {plan.totals.protein} г · Ж {plan.totals.fat} г · У {plan.totals.carbs} г
            </div>
            {plan.adjusted && (
              <div style={{ fontSize: 11, opacity: 0.55, marginTop: 4 }}>план скорректирован под цель</div>
            )}
          </div>

          {plan.meals.map((m, i) => (
            <RecipeCard
              key={i}
              meal={m}
              have={mealHave(m)}
              status={cookState[i]}
              onCook={(meal) => cookMeal(i, meal)}
            />
          ))}

          <div className="card elev-sm" style={{ padding: 14, marginTop: 16 }}>
            <div className="meal-head" style={{ marginBottom: 4 }}>
              <span className="section-head" style={{ margin: 0, flex: 1 }}>Список покупок</span>
              <span className="tag tag-neutral">план → холодильник</span>
            </div>

            {plan.shopping_list.length === 0 ? (
              <div className="state-msg" style={{ padding: "10px 0" }}>Всё нужное уже есть дома.</div>
            ) : (
              groups.map((g) => (
                <div key={g.cat}>
                  <div className="cat-line" style={{ marginTop: 12 }}>
                    <span className="cat-name">{catLabel(g.cat)}</span>
                    <span className="cat-rule" />
                  </div>
                  {g.items.map((s) => {
                    const done = s.have || !!ticked[s.name];
                    return (
                      <label
                        key={s.name}
                        style={{ display: "flex", alignItems: "center", gap: 10, padding: "7px 4px", cursor: s.have ? "default" : "pointer" }}
                      >
                        <input
                          type="checkbox"
                          disabled={s.have}
                          checked={done}
                          onChange={() => setTicked((t) => ({ ...t, [s.name]: !t[s.name] }))}
                        />
                        <span style={{ flex: 1, textDecoration: done ? "line-through" : "none", opacity: done ? 0.55 : 1 }}>
                          {s.name}
                        </span>
                        {s.have ? (
                          <span className="tag tag-accent-2">есть дома</span>
                        ) : (
                          <span className="product-amount">{s.amount} {s.unit}</span>
                        )}
                      </label>
                    );
                  })}
                </div>
              ))
            )}

            <button className="btn btn-secondary btn-block" style={{ marginTop: 16 }} onClick={copyList}>
              {copied ? "Скопировано ✓" : "Копировать список"}
            </button>
          </div>
        </>
      )}
    </div>
  );
}

export default function Plan() {
  const [tab, setTab] = useState("plan");

  return (
    <div>
      <div className="seg-ctl" style={{ marginBottom: 12 }}>
        <button
          className={"seg-ctl-btn" + (tab === "plan" ? " is-on" : "")}
          onClick={() => setTab("plan")}
        >
          План на день
        </button>
        <button
          className={"seg-ctl-btn" + (tab === "recipes" ? " is-on" : "")}
          onClick={() => setTab("recipes")}
        >
          Мои рецепты
        </button>
      </div>

      {tab === "plan" ? <DayPlanView /> : <MyRecipes />}
    </div>
  );
}
