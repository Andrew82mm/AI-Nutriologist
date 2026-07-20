import { useEffect, useState } from "react";
import { api } from "../api";

// Canonical units (g/ml/piece) → Russian display labels.
const UNIT_LABEL = { g: "г", ml: "мл", piece: "шт" };

function formatAmount(amount, unit) {
  const n = Number.isInteger(amount) ? amount : Math.round(amount * 10) / 10;
  return `${n} ${UNIT_LABEL[unit] || unit || ""}`.trim();
}

export default function Fridge() {
  const [items, setItems] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    api
      .getInventory()
      .then(setItems)
      .catch((e) => setError(e.message));
  }, []);

  if (error) return <div className="state-msg">Ошибка загрузки: {error}</div>;
  if (items === null) return <div className="state-msg">Загрузка…</div>;
  if (items.length === 0)
    return <div className="state-msg">Холодильник пуст — добавьте продукты через чат.</div>;

  // Group by category, preserving first-seen order.
  const groups = [];
  const byCat = new Map();
  for (const it of items) {
    const cat = it.category || "прочее";
    if (!byCat.has(cat)) {
      byCat.set(cat, []);
      groups.push(cat);
    }
    byCat.get(cat).push(it);
  }

  return (
    <div>
      {groups.map((cat) => (
        <div key={cat}>
          <div className="cat-head">{cat}</div>
          {byCat.get(cat).map((it) => (
            <div className="item-row" key={it.product_id}>
              <span className="item-name">{it.name}</span>
              <span className="item-amount">{formatAmount(it.amount, it.unit)}</span>
            </div>
          ))}
        </div>
      ))}
    </div>
  );
}
