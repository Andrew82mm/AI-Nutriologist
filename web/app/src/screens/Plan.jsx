// Plan (План) — meal-plan + shopping list. The backend has no meal-planning
// engine yet (no endpoint), so this screen still shows the prototype's static
// example. It is intentionally NOT wired to the API; connecting it needs a
// planner service on the backend first. Kept visible so the shell is complete.

const PLAN_MEALS = [
  { slot: "Завтрак", dish: "Творог 5% с абрикосом и мёдом", kcal: 420, home: true },
  { slot: "Обед", dish: "Гречка с куриным филе", kcal: 650, home: false },
  { slot: "Перекус", dish: "Молоко 2,5% и яйцо", kcal: 260, home: true },
  { slot: "Ужин", dish: "Жаркое (картофель + говядина)", kcal: 850, home: true },
];

export default function Plan() {
  return (
    <div>
      <div className="note">
        Демо-данные. Движок планирования меню на бэкенде пока не реализован — этот экран
        подключим, когда появится соответствующий эндпоинт.
      </div>
      {PLAN_MEALS.map((m) => (
        <div className="meal-card" key={m.slot}>
          <div className="meal-head">
            <span className="meal-title">{m.slot}</span>
            <span className="meal-kcal">{m.kcal} ккал</span>
          </div>
          <div className="meal-items">{m.dish}</div>
          <span
            className={"tag " + (m.home ? "tag-accent-2" : "tag-neutral")}
            style={{ marginTop: 8 }}
          >
            {m.home ? "есть дома" : "докупить"}
          </span>
        </div>
      ))}
    </div>
  );
}
