import { useState } from "react";

// Add/edit form for a meal, matching the prototype: a card with one row per
// position (name + kcal/Б/Ж/У), "+ Ещё блюдо", and submit. In edit mode it also
// shows a delete button. Purely macros-by-hand — see the backend's manual meal
// endpoints.

let _rid = 0;
const emptyRow = () => ({ id: "r" + _rid++, name: "", kcal: "", b: "", zh: "", u: "" });

function toRows(initialItems) {
  if (!initialItems || initialItems.length === 0) return [emptyRow()];
  return initialItems.map((it) => ({
    id: "r" + _rid++,
    name: it.name,
    kcal: String(it.kcal ?? ""),
    b: String(it.protein ?? ""),
    zh: String(it.fat ?? ""),
    u: String(it.carbs ?? ""),
  }));
}

const num = (v) => Math.max(0, Math.round(parseFloat(String(v).replace(",", ".")) || 0));

export default function MealForm({ mode, initialItems, onSave, onDelete, onCancel }) {
  const [rows, setRows] = useState(() => toRows(initialItems));
  const [busy, setBusy] = useState(false);

  const editing = mode === "edit";
  const setField = (id, k, v) =>
    setRows((rs) => rs.map((r) => (r.id === id ? { ...r, [k]: v } : r)));
  const addRow = () => setRows((rs) => [...rs, emptyRow()]);
  const removeRow = (id) => setRows((rs) => (rs.length > 1 ? rs.filter((r) => r.id !== id) : rs));

  const submit = async () => {
    const items = rows
      .filter((r) => r.name.trim() && num(r.kcal))
      .map((r) => ({ name: r.name.trim(), kcal: num(r.kcal), protein: num(r.b), fat: num(r.zh), carbs: num(r.u) }));
    if (items.length === 0) return;
    setBusy(true);
    try {
      await onSave(items);
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

      {rows.map((r, i) => (
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
            onChange={(e) => setField(r.id, "name", e.target.value)}
            placeholder="Блюдо — например, Борщ"
          />
          <div className="meal-form-nums">
            {[["kcal", "ккал", 1.3], ["b", "Б", 1], ["zh", "Ж", 1], ["u", "У", 1]].map(([k, ph, flex]) => (
              <input
                key={k}
                className="input meal-form-num"
                type="number"
                value={r[k]}
                onChange={(e) => setField(r.id, k, e.target.value)}
                placeholder={ph}
                aria-label={ph}
                style={{ flex }}
              />
            ))}
          </div>
        </div>
      ))}

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
