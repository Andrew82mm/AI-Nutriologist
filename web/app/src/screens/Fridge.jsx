import { useEffect, useState } from "react";
import { api } from "../api";
import CookForm from "../CookForm";
import { IconTrash } from "../Icons";

const UNIT_LABEL = { g: "г", ml: "мл", piece: "шт" };
// Display order + labels for category groups and the add-form chips.
const CATS = [
  ["молочное", "Молочное"],
  ["мясо", "Мясо"],
  ["овощи", "Овощи"],
  ["фрукты", "Фрукты"],
  ["крупы/макароны", "Крупы"],
  ["блюда", "Готовые блюда"],
];
const CAT_LABEL = Object.fromEntries(CATS);
const ADD_UNITS = [["г", "g"], ["мл", "ml"], ["шт", "piece"]];

const isLow = (it) => (it.unit === "piece" ? it.amount < 3 : it.amount < 250);
const fmt = (amount, unit) => `${Math.round(amount)} ${UNIT_LABEL[unit] || unit || ""}`.trim();

function ReceiptBanner({ receipt }) {
  if (!receipt || !receipt.store_name) return null;
  return (
    <div className="receipt-banner">
      <span className="receipt-icon">
        <svg width="19" height="19" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round">
          <path d="M4 2v20l2-1 2 1 2-1 2 1 2-1 2 1 2-1 2 1V2l-2 1-2-1-2 1-2-1-2 1-2-1-2 1-2-1z" />
          <path d="M8 7h8M8 11h8M8 15h5" />
        </svg>
      </span>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div className="receipt-title">Обработан чек из «{receipt.store_name}»{receipt.date ? ` за ${receipt.date}` : ""}</div>
        <div className="receipt-sub">Добавлено +{receipt.items_added} продуктов в холодильник</div>
      </div>
    </div>
  );
}

function AddProductForm({ onAdd, onCancel }) {
  const [name, setName] = useState("");
  const [amount, setAmount] = useState("");
  const [unit, setUnit] = useState("g");
  const [category, setCategory] = useState("овощи");
  const [busy, setBusy] = useState(false);

  const submit = async () => {
    if (!name.trim()) return;
    const amt = Math.max(0, Math.round(parseFloat(String(amount).replace(",", ".")) || 0));
    setBusy(true);
    try {
      await onAdd({
        name: name.trim(),
        grams: amt,
        amount_canonical: amt,
        canonical_unit: unit,
        category,
        per100: [0, 0, 0, 0],
      });
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="meal-form card elev-sm">
      <div className="meal-form-head">
        <span className="meal-form-title">Добавить продукт или блюдо</span>
        <button className="btn btn-icon btn-secondary" style={{ width: 32, height: 32 }} onClick={onCancel} aria-label="Отмена">✕</button>
      </div>
      <input className="input" value={name} onChange={(e) => setName(e.target.value)} placeholder="Например, Жаркое или Йогурт" />
      <div className="add-amount-row">
        <input className="input" type="number" value={amount} onChange={(e) => setAmount(e.target.value)} placeholder="Кол-во" style={{ flex: 1 }} />
        <div className="seg">
          {ADD_UNITS.map(([label, val]) => (
            <label className="seg-opt" key={val}>
              <input type="radio" name="addunit" checked={unit === val} onChange={() => setUnit(val)} />
              {label}
            </label>
          ))}
        </div>
      </div>
      <div className="add-cats">
        {CATS.map(([val, label]) => (
          <button
            key={val}
            className={"chip-btn" + (category === val ? " is-on" : "")}
            onClick={() => setCategory(val)}
          >
            {label}
          </button>
        ))}
      </div>
      <button className="btn btn-primary btn-block" onClick={submit} disabled={busy}>Добавить в холодильник</button>
    </div>
  );
}

function ProductCard({ item, onAction }) {
  // Eating is logged in the diary (which draws stock down); cooking lives in the
  // "add product or dish" form. The card is about stock, so it keeps only the
  // stock-only write-off. See api/inventory.inventory_action.
  return (
    <div className="card elev-sm product-card">
      <div className="product-head">
        <span className="product-name">{item.name}</span>
        {isLow(item) && <span className="tag tag-neutral" style={{ fontSize: 10 }}>мало</span>}
        <span className="product-amount">{fmt(item.amount, item.unit)}</span>
        <button
          className="product-trash"
          onClick={() => onAction(item, "trash")}
          aria-label={`Выкинуть: ${item.name}`}
          title="Выкинуть"
        >
          <IconTrash />
        </button>
      </div>
    </div>
  );
}

export default function Fridge({ reloadKey, onChanged }) {
  const [items, setItems] = useState(null);
  const [receipt, setReceipt] = useState(null);
  const [error, setError] = useState(null);
  const [adding, setAdding] = useState(null); // null | 'product' | 'dish'

  useEffect(() => {
    setError(null);
    api.getInventory().then(setItems).catch((e) => setError(e.message));
    api.getLastReceipt().then(setReceipt).catch(() => {});
  }, [reloadKey]);

  const changed = () => onChanged?.(); // bump parent reloadKey → refetch here + diary

  const doAction = async (item, action) => {
    await api.inventoryAction(item.product_id, action);
    changed();
  };
  const addProduct = async (item) => {
    await api.addInventory([item]);
    setAdding(null);
    changed();
  };
  const cook = async (name, ingredients, yieldGrams) => {
    await api.cook(name, ingredients, yieldGrams);
    setAdding(null);
    changed();
  };

  if (error) return <div className="state-msg">Ошибка загрузки: {error}</div>;
  if (items === null) return <div className="state-msg">Загрузка…</div>;

  // Group by category in display order; unknown categories appended.
  const groups = [];
  const known = new Set(CATS.map(([v]) => v));
  for (const [cat] of CATS) {
    const list = items.filter((it) => (it.category || "прочее") === cat);
    if (list.length) groups.push([cat, list]);
  }
  const otherCats = [...new Set(items.map((it) => it.category || "прочее").filter((c) => !known.has(c)))];
  for (const cat of otherCats) groups.push([cat, items.filter((it) => (it.category || "прочее") === cat)]);

  return (
    <div className="fridge">
      <ReceiptBanner receipt={receipt} />

      {adding ? (
        <>
          <div className="seg add-mode-seg" style={{ display: "flex" }}>
            <label className="seg-opt" style={{ flex: 1, justifyContent: "center" }}>
              <input type="radio" name="addmode" checked={adding === "product"} onChange={() => setAdding("product")} />
              Продукт
            </label>
            <label className="seg-opt" style={{ flex: 1, justifyContent: "center" }}>
              <input type="radio" name="addmode" checked={adding === "dish"} onChange={() => setAdding("dish")} />
              Блюдо
            </label>
          </div>
          {adding === "product" ? (
            <AddProductForm onAdd={addProduct} onCancel={() => setAdding(null)} />
          ) : items.length === 0 ? (
            <div className="meal-form card elev-sm">
              <div className="meal-form-head">
                <span className="meal-form-title">Приготовить блюдо</span>
                <button className="btn btn-icon btn-secondary" style={{ width: 32, height: 32 }} onClick={() => setAdding(null)} aria-label="Отмена">✕</button>
              </div>
              <div className="state-msg" style={{ padding: "8px 0" }}>Сначала добавьте продукты в холодильник — блюдо готовится из них.</div>
            </div>
          ) : (
            <CookForm inventory={items} onCook={cook} onCancel={() => setAdding(null)} />
          )}
        </>
      ) : (
        <>
          <button className="btn btn-secondary btn-block" style={{ gap: 8, borderStyle: "dashed" }} onClick={() => setAdding("product")}>
            + Добавить продукт или блюдо
          </button>
        </>
      )}

      {items.length === 0 ? (
        <div className="state-msg">Холодильник пуст — добавьте продукты.</div>
      ) : (
        groups.map(([cat, list]) => (
          <div className="fridge-group" key={cat}>
            <div className="cat-line">
              <span className="cat-name">{CAT_LABEL[cat] || cat}</span>
              <span className="cat-rule" />
              <span className="cat-count">{list.length} поз.</span>
            </div>
            {list.map((it) => (
              <ProductCard key={it.product_id} item={it} onAction={doAction} />
            ))}
          </div>
        ))
      )}
    </div>
  );
}
