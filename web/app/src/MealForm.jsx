import { useEffect, useRef, useState } from "react";
import { api } from "./api";

// Add/edit form for a meal. You type a name + amount per position; the backend
// estimates КБЖУ (local base → LLM → «?») and tells us the product's unit and
// whether it's in the fridge. Macros are shown, not typed — but any position can
// be overridden by hand (which the backend then learns). Saving commits through
// the one canonical path, POST /api/meals (same as chat). See api/actions.py.

let _rid = 0;
const emptyRow = () => ({
  id: "r" + _rid++, name: "", amount: "",
  unit: "g", unitLabel: "г", grams: 0, amountCanonical: 0,
  per100: null, kcal: null, protein: null, fat: null, carbs: null,
  known: null, inFridge: false, category: null,
  ov: { on: false, kcal: "", b: "", zh: "", u: "" },
});

// Time-of-day default, mirroring the backend (api/diary.title_for_hour).
export function defaultMealTitle(d = new Date()) {
  const h = d.getHours();
  return h < 11 ? "Завтрак" : h < 16 ? "Обед" : h < 21 ? "Ужин" : "Перекус";
}

const num = (v) => Math.max(0, parseFloat(String(v).replace(",", ".")) || 0);

// A saved diary item → a prefilled row (backend re-estimates unit/fridge on mount).
function rowFromItem(it) {
  const amount = it.amount_canonical ?? it.grams;
  return {
    id: "r" + _rid++, name: it.name, amount: String(Math.round(amount)),
    unit: it.unit || "g", unitLabel: { g: "г", ml: "мл", piece: "шт" }[it.unit] || "г",
    grams: it.grams, amountCanonical: amount,
    per100: null,
    kcal: it.known ? it.kcal : null, protein: it.known ? it.protein : null,
    fat: it.known ? it.fat : null, carbs: it.known ? it.carbs : null,
    known: it.known, inFridge: false, category: null,
    ov: { on: false, kcal: "", b: "", zh: "", u: "" },
  };
}

export default function MealForm({ mode, initialItems, initialTitle, onSave, onDelete, onCancel }) {
  const [rows, setRows] = useState(() =>
    initialItems && initialItems.length ? initialItems.map(rowFromItem) : [emptyRow()]
  );
  const [title, setTitle] = useState(initialTitle || "");
  const [busy, setBusy] = useState(false);
  const reqId = useRef(0);

  const editing = mode === "edit";
  const setRow = (id, patch) =>
    setRows((rs) => rs.map((r) => (r.id === id ? { ...r, ...patch } : r)));
  const setOv = (id, k, v) =>
    setRows((rs) => rs.map((r) => (r.id === id ? { ...r, ov: { ...r.ov, [k]: v } } : r)));
  const addRow = () => setRows((rs) => [...rs, emptyRow()]);
  const removeRow = (id) => setRows((rs) => (rs.length > 1 ? rs.filter((r) => r.id !== id) : rs));

  // Debounced estimate whenever any name/amount changes. Merges results by index;
  // never clobbers a row the user is actively overriding.
  const key = rows.map((r) => `${r.name}|${r.amount}`).join("~");
  useEffect(() => {
    const payload = rows.map((r) => ({
      name: r.name.trim(),
      amount: r.amount === "" ? null : num(r.amount),
    }));
    if (payload.every((p) => !p.name)) return;
    const my = ++reqId.current;
    const t = setTimeout(async () => {
      try {
        const { items } = await api.estimateMeal(payload);
        if (my !== reqId.current) return;
        setRows((rs) =>
          rs.map((r, i) => {
            const e = items[i];
            if (!e || !r.name.trim()) return r;
            return {
              ...r,
              unit: e.canonical_unit, unitLabel: e.unit_label,
              grams: e.grams, amountCanonical: e.amount_canonical,
              per100: e.per100, kcal: e.kcal, protein: e.protein, fat: e.fat, carbs: e.carbs,
              known: e.known, inFridge: e.in_fridge, category: e.category,
              // Auto-open manual entry for unknowns not already being overridden.
              ov: e.known || r.ov.on ? r.ov : { on: true, kcal: "", b: "", zh: "", u: "" },
            };
          })
        );
      } catch {
        /* estimate is best-effort; leave rows as-is */
      }
    }, 450);
    return () => clearTimeout(t);
  }, [key]); // eslint-disable-line react-hooks/exhaustive-deps

  const startOverride = (r) => {
    // Prefill with the product's per-100 g values (what the fields now expect),
    // not the portion estimate.
    const p = r.per100 || [null, null, null, null];
    setRow(r.id, {
      ov: {
        on: true,
        kcal: p[0] != null ? String(p[0]) : "",
        b: p[1] != null ? String(p[1]) : "",
        zh: p[2] != null ? String(p[2]) : "",
        u: p[3] != null ? String(p[3]) : "",
      },
    });
  };

  const submit = async () => {
    const items = [];
    for (const r of rows) {
      const name = r.name.trim();
      const amount = num(r.amount);
      if (!name || amount <= 0) continue;
      const grams = r.grams || (r.unit === "piece" ? amount * 100 : amount);
      let per100 = [0, 0, 0, 0];
      let source = "db";
      const ovHas = r.ov.on && (r.ov.kcal || r.ov.b || r.ov.zh || r.ov.u);
      if (ovHas) {
        // Hand-entered macros are per 100 g (like food labels) — stored as-is;
        // the diary scales them to the portion by grams.
        per100 = [num(r.ov.kcal), num(r.ov.b), num(r.ov.zh), num(r.ov.u)];
        source = "user";
      } else if (r.known && r.per100) {
        per100 = r.per100;
      }
      items.push({
        name, grams, amount_canonical: r.amountCanonical || amount,
        unit: r.unitLabel, canonical_unit: r.unit, category: r.category,
        per100, per100_source: source,
      });
    }
    if (items.length === 0) return;
    setBusy(true);
    try {
      await onSave(items, title.trim() || null);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="meal-form card elev-sm">
      <div className="meal-form-head">
        <span className="meal-form-title">{editing ? "Редактировать приём пищи" : "Добавить приём пищи"}</span>
        <button className="btn btn-icon btn-secondary" style={{ width: 32, height: 32 }} onClick={onCancel} aria-label="Отмена">✕</button>
      </div>

      <div className="meal-form-name">
        <span className="meal-form-pos">Название приёма</span>
        <input
          className="input"
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          placeholder={defaultMealTitle() + " — по времени, можно своё"}
        />
      </div>

      {rows.map((r, i) => {
        const hasMacros = r.known && r.kcal != null && !r.ov.on;
        return (
          <div className="meal-form-row" key={r.id}>
            <div className="meal-form-rowhead">
              <span className="meal-form-pos">Позиция {i + 1}</span>
              {rows.length > 1 && (
                <button className="meal-form-x" onClick={() => removeRow(r.id)} aria-label="Удалить позицию">✕</button>
              )}
            </div>
            <input
              className="input"
              value={r.name}
              onChange={(e) => setRow(r.id, { name: e.target.value })}
              placeholder="Блюдо — например, Борщ или Шаурма"
            />

            <div className="meal-amount-row">
              <div className="meal-amount-field">
                <input
                  className="input"
                  type="number"
                  value={r.amount}
                  onChange={(e) => setRow(r.id, { amount: e.target.value })}
                  placeholder="Кол-во"
                  aria-label="количество"
                />
                <span className="meal-amount-unit">{r.unitLabel}</span>
              </div>
              {/* estimated macros / «?» */}
              {hasMacros ? (
                <span className="meal-macro-preview">
                  ≈ <b>{r.kcal}</b> ккал · Б {r.protein} · Ж {r.fat} · У {r.carbs}
                  <button className="meal-macro-edit" onClick={() => startOverride(r)}>изменить</button>
                </span>
              ) : r.known === false && !r.ov.on ? (
                <span className="meal-macro-preview meal-macro-unknown">
                  КБЖУ неизвестно · <b>?</b>
                  <button className="meal-macro-edit" onClick={() => startOverride(r)}>ввести</button>
                </span>
              ) : null}
            </div>

            {r.ov.on && (
              <div className="meal-form-nums">
                <span className="meal-form-pos" style={{ flexBasis: "100%", marginBottom: 2 }}>
                  КБЖУ на 100 г
                </span>
                {[["kcal", "ккал", 1.3], ["b", "Б", 1], ["zh", "Ж", 1], ["u", "У", 1]].map(([k, ph, flex]) => (
                  <input
                    key={k}
                    className="input meal-form-num"
                    type="number"
                    value={r.ov[k]}
                    onChange={(e) => setOv(r.id, k, e.target.value)}
                    placeholder={ph}
                    aria-label={ph}
                    style={{ flex }}
                  />
                ))}
              </div>
            )}

            {/* fridge drawdown hint */}
            {r.name.trim() && r.known !== null && (
              <span className={"meal-fridge-hint" + (r.inFridge ? " is-fridge" : "")}>
                {r.inFridge
                  ? `спишется из холодильника: −${Math.round(r.amountCanonical || 0)} ${r.unitLabel}`
                  : "вне холодильника"}
              </span>
            )}
          </div>
        );
      })}

      <button className="btn btn-ghost meal-form-more" onClick={addRow}>+ Ещё блюдо</button>

      <div className="meal-form-actions">
        {editing && (
          <button className="btn btn-secondary meal-form-del" onClick={onDelete} aria-label="Удалить приём">🗑</button>
        )}
        <button className="btn btn-primary" style={{ flex: 1 }} onClick={submit} disabled={busy}>
          {editing ? "Сохранить" : "Записать приём"}
        </button>
      </div>
    </div>
  );
}
