import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import { IconMail } from "../Icons";

const GOAL_TYPES = ["Похудение", "Поддержание", "Набор"];
const ACTIVITIES = ["низкая", "средняя", "высокая"];
const ACTIVITY_LABELS = { "низкая": "Низкая", "средняя": "Средняя", "высокая": "Высокая" };

// Theme options for the settings segmented control (value → visible label).
const THEMES = [["light", "Светлая"], ["dark", "Тёмная"], ["system", "Сист."]];

// A connected segmented control: one filled pill slides to the active option.
function Seg({ options, value, onPick }) {
  return (
    <div className="seg-ctl">
      {options.map(([val, label]) => (
        <button
          key={val}
          className={"seg-ctl-btn" + (value === val ? " is-on" : "")}
          onClick={() => onPick(val)}
        >
          {label}
        </button>
      ))}
    </div>
  );
}

export default function Profile({ theme, onThemeChange }) {
  const [p, setP] = useState(null);
  const [status, setStatus] = useState("");
  const [goalNotes, setGoalNotes] = useState([]);
  // Email connection is a client-only feature (no backend yet): kept in
  // localStorage so it survives reloads. `emailDraft` is the inline connect form.
  const [email, setEmail] = useState(() => localStorage.getItem("connectedEmail") || "");
  const [emailDraft, setEmailDraft] = useState(null);
  // Inline "add restriction" field: null = closed, string = the text being typed.
  const [restrDraft, setRestrDraft] = useState(null);
  const recalcTimer = useRef(null);

  useEffect(() => {
    api.getProfile().then(setP).catch((e) => setStatus("Ошибка: " + e.message));
    return () => clearTimeout(recalcTimer.current);
  }, []);

  if (p === null) return <div className="state-msg">{status || "Загрузка…"}</div>;

  // Recompute the calorie goal from body + goal type whenever the profile
  // changes (Mifflin-St Jeor). Debounced so typing weight/age doesn't spam the
  // API; the goal fields stay editable, so a manual edit sticks until the next
  // body change. Never fires on initial load — only on an explicit user change.
  const recalcGoal = (body, goalType) => {
    clearTimeout(recalcTimer.current);
    recalcTimer.current = setTimeout(() => {
      api
        .computeGoal(body, goalType)
        .then(({ notes = [], ...goal }) => {
          setP((prev) => (prev ? { ...prev, goal } : prev));
          setGoalNotes(notes);
        })
        .catch(() => {});
    }, 400);
  };

  const setGoal = (k, v) => setP({ ...p, goal: { ...p.goal, [k]: Number(v) || 0 } });
  const setBody = (k, v) => {
    const body = { ...p.body, [k]: v };
    setP({ ...p, body });
    recalcGoal(body, p.goal_type);
  };
  const setGoalType = (v) => {
    setP({ ...p, goal_type: v });
    recalcGoal(p.body, v);
  };
  const addRestr = () => {
    const v = (restrDraft || "").trim();
    if (v && !p.restrictions.includes(v)) {
      setP({ ...p, restrictions: [...p.restrictions, v] });
    }
    setRestrDraft(null);
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

  const connectEmail = () => {
    const value = (emailDraft || "").trim();
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(value)) return;
    localStorage.setItem("connectedEmail", value);
    setEmail(value);
    setEmailDraft(null);
  };
  const disconnectEmail = () => {
    localStorage.removeItem("connectedEmail");
    setEmail("");
  };

  // No server-side delete endpoint exists yet — this clears the locally-stored
  // settings (theme + connected email) after confirmation, and says so.
  const clearLocalData = () => {
    if (!window.confirm("Очистить локальные настройки (тема, подключённая почта)? Данные профиля на сервере не затрагиваются.")) return;
    localStorage.removeItem("connectedEmail");
    localStorage.removeItem("theme");
    setEmail("");
    onThemeChange("light");
    setStatus("Локальные настройки очищены");
    setTimeout(() => setStatus(""), 2000);
  };

  const exportData = () => {
    const blob = new Blob([JSON.stringify(p, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "nutriologist-profile.json";
    a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div className="profile">
      {/* ── Цель ─────────────────────────────────────────────── */}
      <section className="set-section">
        <div className="set-label">Цель</div>
        <div className="set-card">
          <Seg options={GOAL_TYPES.map((g) => [g, g])} value={p.goal_type} onPick={setGoalType} />

          <div className="set-row">
            <span className="set-row-label">Калории в день</span>
            <div className="set-pill">
              <input
                className="input"
                type="number"
                value={p.goal.kcal}
                onChange={(e) => setGoal("kcal", e.target.value)}
              />
            </div>
          </div>

          <div className="set-grid">
            {[["protein", "Б", "белки", "var(--mc-b)"], ["fat", "Ж", "жиры", "var(--mc-zh)"], ["carbs", "У", "углев.", "var(--mc-u)"]].map(
              ([key, letter, word, color]) => (
                <div className="set-field" key={key}>
                  <label>
                    <span style={{ color, fontWeight: 700 }}>{letter}</span> {word}
                  </label>
                  <input
                    className="input"
                    type="number"
                    value={p.goal[key]}
                    onChange={(e) => setGoal(key, e.target.value)}
                  />
                </div>
              )
            )}
          </div>

          {goalNotes.length > 0 && (
            <div className="set-warn">
              {goalNotes.map((n, i) => (
                <div key={i}>⚠️ {n}</div>
              ))}
            </div>
          )}
          <div className="set-hint">
            Калории рассчитываются автоматически по формуле Миффлина — Сан-Жеора.
            Можно поправить вручную.
          </div>
        </div>
      </section>

      {/* ── Параметры тела ───────────────────────────────────── */}
      <section className="set-section">
        <div className="set-label">Параметры тела</div>
        <div className="set-card">
          <Seg options={[["М", "Мужской"], ["Ж", "Женский"]]} value={p.body.sex} onPick={(v) => setBody("sex", v)} />

          <div className="set-grid">
            {[["age", "Возраст, лет"], ["height", "Рост, см"], ["weight", "Вес, кг"]].map(([key, label]) => (
              <div className="set-field" key={key}>
                <label>{label}</label>
                <input
                  className="input"
                  type="number"
                  value={p.body[key]}
                  onChange={(e) => setBody(key, Number(e.target.value) || 0)}
                />
              </div>
            ))}
          </div>

          <div className="set-field">
            <label>Уровень активности</label>
            <Seg
              options={ACTIVITIES.map((a) => [a, ACTIVITY_LABELS[a]])}
              value={p.body.activity}
              onPick={(v) => setBody("activity", v)}
            />
          </div>
        </div>
      </section>

      {/* ── Ограничения и предпочтения ───────────────────────── */}
      <section className="set-section">
        <div className="set-label">Ограничения и предпочтения</div>
        <div className="set-card">
          <div className="restr-list">
            {p.restrictions.map((r) => (
              <button key={r} className="restr-chip" onClick={() => removeRestr(r)} title="Убрать">
                {r} <span className="restr-x">✕</span>
              </button>
            ))}
            {restrDraft === null && (
              <button className="restr-add" onClick={() => setRestrDraft("")}>+ Добавить</button>
            )}
          </div>
          {restrDraft !== null && (
            <div className="set-mail-form">
              <input
                className="input"
                type="text"
                placeholder="Например: Без рыбы"
                autoFocus
                value={restrDraft}
                onChange={(e) => setRestrDraft(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") addRestr();
                  if (e.key === "Escape") setRestrDraft(null);
                }}
              />
              <button className="btn btn-primary" onClick={addRestr}>Ок</button>
              <button className="btn btn-secondary" onClick={() => setRestrDraft(null)}>Отмена</button>
            </div>
          )}
          <div className="set-hint">Влияет на план меню и советы рецептов.</div>
        </div>
      </section>

      <button className="btn btn-primary btn-block" onClick={save}>Сохранить</button>
      {status && <div className="set-status">{status}</div>}

      {/* ── Настройки ────────────────────────────────────────── */}
      <section className="set-section">
        <div className="set-label">Настройки</div>
        <div className="set-card">
          <div className="set-row">
            <span className="set-row-label">Тема</span>
            <Seg options={THEMES} value={theme} onPick={onThemeChange} />
          </div>

          <div className="set-row">
            <span className="set-row-label">Единицы</span>
            <span className="set-units">метрические · г / мл / ккал</span>
          </div>

          {email ? (
            <div className="set-mail-connected">
              <span className="set-mail-icon"><IconMail /></span>
              <span className="set-mail-addr">{email}</span>
              <button className="btn btn-ghost set-mail-off" onClick={disconnectEmail}>Отключить</button>
            </div>
          ) : emailDraft !== null ? (
            <div className="set-mail-form">
              <input
                className="input"
                type="email"
                placeholder="you@example.com"
                autoFocus
                value={emailDraft}
                onChange={(e) => setEmailDraft(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && connectEmail()}
              />
              <button className="btn btn-primary" onClick={connectEmail}>Ок</button>
              <button className="btn btn-secondary" onClick={() => setEmailDraft(null)}>Отмена</button>
            </div>
          ) : (
            <button className="btn btn-secondary set-mail-btn" onClick={() => setEmailDraft("")}>
              <IconMail size={17} /> Подключить почту
            </button>
          )}

          <div className="set-actions">
            <button className="btn btn-secondary" onClick={exportData}>Экспорт данных</button>
            <button className="btn btn-secondary" onClick={clearLocalData}>Удалить данные</button>
          </div>

          <div className="set-row set-about">
            <span className="set-row-label">О приложении</span>
            <span className="set-units">v1.0</span>
          </div>
          <div className="set-hint">Информация справочная, не медицинская рекомендация.</div>
        </div>
      </section>
    </div>
  );
}
