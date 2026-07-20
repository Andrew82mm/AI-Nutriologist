import { useState } from "react";

// "Приготовил" modal: pick ingredients from what's in the fridge + their weight,
// name the dish. On submit the ingredients are consumed and the finished dish is
// stocked with its computed КБЖУ (backend POST /api/cook).

const UNIT_LABEL = { g: "г", ml: "мл", piece: "шт" };
let _cid = 0;

const num = (v) => Math.max(0, Math.round(parseFloat(String(v).replace(",", ".")) || 0));

export default function CookForm({ inventory, initialProductId, onCook, onCancel }) {
  const [name, setName] = useState("");
  const [yieldGrams, setYieldGrams] = useState("");
  const [rows, setRows] = useState(() => {
    const first = inventory.find((x) => x.product_id === initialProductId) || inventory[0];
    return [{ id: "c" + _cid++, productId: first ? first.product_id : "", grams: "" }];
  });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  const setRow = (id, k, v) => setRows((rs) => rs.map((r) => (r.id === id ? { ...r, [k]: v } : r)));
  const addRow = () => setRows((rs) => [...rs, { id: "c" + _cid++, productId: inventory[0]?.product_id || "", grams: "" }]);
  const removeRow = (id) => setRows((rs) => (rs.length > 1 ? rs.filter((r) => r.id !== id) : rs));

  const submit = async () => {
    const ingredients = rows
      .filter((r) => r.productId && num(r.grams))
      .map((r) => ({ product_id: Number(r.productId), grams: num(r.grams) }));
    if (!name.trim()) return setError("Введите название блюда");
    if (ingredients.length === 0) return setError("Добавьте хотя бы один ингредиент с весом");
    setBusy(true);
    setError(null);
    try {
      await onCook(name.trim(), ingredients, num(yieldGrams) || null);
    } catch (e) {
      setError(e.message);
      setBusy(false);
    }
  };

  return (
    <div className="meal-form card elev-sm">
      <div className="meal-form-head">
        <span className="meal-form-title">Приготовить блюдо</span>
        <button className="btn btn-icon btn-secondary" style={{ width: 32, height: 32 }} onClick={onCancel} aria-label="Отмена">✕</button>
      </div>

      <div className="meal-form-name">
        <span className="meal-form-pos">Название блюда</span>
        <input className="input" value={name} onChange={(e) => setName(e.target.value)} placeholder="Например, Гречка с курицей" />
      </div>

      <span className="meal-form-pos">Ингредиенты из холодильника</span>
      {rows.map((r) => {
        const prod = inventory.find((x) => String(x.product_id) === String(r.productId));
        return (
          <div className="cook-row" key={r.id}>
            <select className="input" value={r.productId} onChange={(e) => setRow(r.id, "productId", e.target.value)}>
              {inventory.map((x) => (
                <option key={x.product_id} value={x.product_id}>
                  {x.name} ({Math.round(x.amount)} {UNIT_LABEL[x.unit] || x.unit})
                </option>
              ))}
            </select>
            <input
              className="input cook-grams"
              type="number"
              value={r.grams}
              onChange={(e) => setRow(r.id, "grams", e.target.value)}
              placeholder={prod && prod.unit === "piece" ? "шт" : "г"}
              aria-label="вес"
            />
            {rows.length > 1 && (
              <button className="meal-form-x" onClick={() => removeRow(r.id)} aria-label="Убрать ингредиент">✕</button>
            )}
          </div>
        );
      })}

      <button className="btn btn-ghost meal-form-more" onClick={addRow}>+ Ещё ингредиент</button>

      <div className="meal-form-name">
        <span className="meal-form-pos">Готовый вес, г (необязательно)</span>
        <input className="input" type="number" value={yieldGrams} onChange={(e) => setYieldGrams(e.target.value)} placeholder="по умолчанию — сумма ингредиентов" />
      </div>

      {error && <div className="cook-error">{error}</div>}

      <button className="btn btn-primary btn-block" onClick={submit} disabled={busy}>
        {busy ? "Готовим…" : "Приготовить"}
      </button>
    </div>
  );
}
