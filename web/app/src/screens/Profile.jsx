import { useEffect, useState } from "react";
import { api } from "../api";

const GOAL_TYPES = ["Похудение", "Поддержание", "Набор"];
const ACTIVITIES = ["низкая", "средняя", "высокая"];
const RESTR_POOL = ["Без глютена", "Вегетарианство", "Без лактозы", "Меньше соли", "Без свинины", "Без арахиса"];

function Chips({ options, value, onPick }) {
  return (
    <div className="segmented">
      {options.map((o) => (
        <button
          key={o}
          className={"chip-btn" + (value === o ? " is-on" : "")}
          onClick={() => onPick(o)}
        >
          {o}
        </button>
      ))}
    </div>
  );
}

export default function Profile() {
  const [p, setP] = useState(null);
  const [status, setStatus] = useState("");

  useEffect(() => {
    api.getProfile().then(setP).catch((e) => setStatus("Ошибка: " + e.message));
  }, []);

  if (p === null) return <div className="state-msg">{status || "Загрузка…"}</div>;

  const setGoal = (k, v) => setP({ ...p, goal: { ...p.goal, [k]: Number(v) || 0 } });
  const setBody = (k, v) => setP({ ...p, body: { ...p.body, [k]: v } });
  const addRestr = () => {
    const next = RESTR_POOL.find((r) => !p.restrictions.includes(r));
    if (next) setP({ ...p, restrictions: [...p.restrictions, next] });
  };
  const removeRestr = (r) => setP({ ...p, restrictions: p.restrictions.filter((x) => x !== r) });

  const save = async () => {
    setStatus("Сохранение…");
    try {
      const saved = await api.putProfile(p);
      setP(saved);
      setStatus("Сохранено ✓");
      setTimeout(() => setStatus(""), 1500);
    } catch (e) {
      setStatus("Ошибка: " + e.message);
    }
  };

  return (
    <div>
      <div className="section-head">Цель по калориям</div>
      {[["Калории", "kcal", "ккал"], ["Белки", "protein", "г"], ["Жиры", "fat", "г"], ["Углеводы", "carbs", "г"]].map(
        ([label, key, unit]) => (
          <div className="form-row" key={key}>
            <label>{label}</label>
            <div>
              <input
                className="input num-input"
                type="number"
                value={p.goal[key]}
                onChange={(e) => setGoal(key, e.target.value)}
              />{" "}
              <span className="macro-val">{unit}</span>
            </div>
          </div>
        )
      )}

      <div className="section-head">Тип цели</div>
      <Chips options={GOAL_TYPES} value={p.goal_type} onPick={(v) => setP({ ...p, goal_type: v })} />

      <div className="section-head">Тело</div>
      <div className="form-row">
        <label>Пол</label>
        <Chips options={["М", "Ж"]} value={p.body.sex} onPick={(v) => setBody("sex", v)} />
      </div>
      {[["Возраст", "age"], ["Рост, см", "height"], ["Вес, кг", "weight"]].map(([label, key]) => (
        <div className="form-row" key={key}>
          <label>{label}</label>
          <input
            className="input num-input"
            type="number"
            value={p.body[key]}
            onChange={(e) => setBody(key, Number(e.target.value) || 0)}
          />
        </div>
      ))}
      <div className="form-row">
        <label>Активность</label>
        <Chips options={ACTIVITIES} value={p.body.activity} onPick={(v) => setBody("activity", v)} />
      </div>

      <div className="section-head">Ограничения</div>
      <div className="restr-list">
        {p.restrictions.map((r) => (
          <button key={r} className="tag tag-accent-2" onClick={() => removeRestr(r)} title="Убрать">
            {r} ✕
          </button>
        ))}
        <button className="chip-btn" onClick={addRestr}>+ добавить</button>
      </div>

      <button className="btn btn-primary btn-block" style={{ marginTop: 24 }} onClick={save}>
        Сохранить
      </button>
      {status && <div className="summary-remaining" style={{ textAlign: "center", marginTop: 8 }}>{status}</div>}
    </div>
  );
}
