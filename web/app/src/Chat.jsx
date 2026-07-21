import { useEffect, useRef, useState } from "react";
import { api } from "./api";

const SUGGESTIONS = [
  "съел два яйца и творог 5% 200 г",
  "купил кило абрикосов",
  "отчёт за день",
  "что приготовить?",
];

const INTRO = {
  id: "intro",
  role: "assistant",
  kind: "text",
  text: "Привет! Напишите, что съели или купили — посчитаю БЖУ и обновлю холодильник. Например: «съел два яйца и творог 5% 200 г», «купил кило абрикосов» или «отчёт за день».",
};

// Renders one assistant response of a given kind. `kind` mirrors the backend's
// `intent` ('eat' | 'buy' | 'report' | 'recipes' | 'unknown'); the client-made
// intro uses 'text'. Anything that isn't a card but carries `.text` is a bubble.
function BotMessage({ msg, onConfirm }) {
  if (msg.kind !== "eat" && msg.kind !== "buy" && msg.kind !== "report" && msg.text) {
    return <div className="bubble bubble-bot" style={{ whiteSpace: "pre-line" }}>{msg.text}</div>;
  }

  if (msg.kind === "report") {
    const r = msg.report;
    return (
      <div className="confirm-card">
        <b>Отчёт за день</b>
        <div className="confirm-item"><span>Калории</span><span>{Math.round(r.consumed.kcal)} / {Math.round(r.goal.kcal)} ккал</span></div>
        <div className="confirm-item"><span>Б / Ж / У</span><span>{r.consumed.protein} / {r.consumed.fat} / {r.consumed.carbs} г</span></div>
        <div className="confirm-item"><span>Осталось</span><span>{r.remaining_kcal} ккал</span></div>
      </div>
    );
  }

  // eat / buy — editable confirmation card
  const isEat = msg.kind === "eat";
  return (
    <div className="confirm-card">
      <b>{isEat ? "Записать в дневник?" : "Добавить в холодильник?"}</b>
      {msg.items.map((it, i) => {
        // Show pieces by count, weight/volume by grams/ml.
        const qty =
          it.unit === "шт"
            ? `${it.amount_canonical ?? it.grams} шт`
            : `${it.grams} ${it.unit || "г"}`;
        return (
          <div className="confirm-item" key={i}>
            <span>{it.name}</span>
            <span>{isEat ? `${qty} · ${Math.round(it.kcal)} ккал` : qty}</span>
          </div>
        );
      })}
      {isEat && msg.total && (
        <div className="confirm-item" style={{ borderTop: "1px solid var(--color-divider)", marginTop: 4, paddingTop: 6 }}>
          <b>Итого</b>
          <b>{msg.total.kcal} ккал</b>
        </div>
      )}
      {msg.done ? (
        <div className="summary-remaining" style={{ marginTop: 8 }}>Готово ✓</div>
      ) : (
        <button className="btn btn-primary btn-block" style={{ marginTop: 10 }} onClick={() => onConfirm(msg)}>
          {isEat ? "Записать приём" : "Добавить"}
        </button>
      )}
    </div>
  );
}

export default function Chat({ onClose, onCommit }) {
  const [messages, setMessages] = useState([INTRO]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const scrollRef = useRef(null);

  useEffect(() => {
    const el = scrollRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [messages]);

  const send = async (text) => {
    const t = (text ?? input).trim();
    if (!t || busy) return;
    setInput("");
    setBusy(true);
    const uid = "u" + Date.now();
    setMessages((m) => [...m, { id: uid, role: "user", kind: "text", text: t }]);
    try {
      const resp = await api.chat(t);
      // The API uses `intent`; the UI switches on `kind`.
      setMessages((m) => [...m, { ...resp, kind: resp.intent, id: "a" + Date.now(), role: "assistant" }]);
    } catch (e) {
      setMessages((m) => [...m, { id: "e" + Date.now(), role: "assistant", kind: "text", text: "Ошибка: " + e.message }]);
    } finally {
      setBusy(false);
    }
  };

  const confirm = async (msg) => {
    try {
      if (msg.kind === "eat") await api.logMeal(msg.items, "", msg.title);
      else if (msg.kind === "buy") await api.addInventory(msg.items);
      setMessages((m) => m.map((x) => (x.id === msg.id ? { ...x, done: true } : x)));
      onCommit?.();
    } catch (e) {
      setMessages((m) => [...m, { id: "e" + Date.now(), role: "assistant", kind: "text", text: "Не удалось сохранить: " + e.message }]);
    }
  };

  const showSuggest = messages.length === 1;

  return (
    <div className="chat-overlay">
      <header className="app-header">
        <div style={{ flex: 1 }}>
          <div className="app-kicker">Ассистент</div>
          <div className="app-title">Чат</div>
        </div>
        <button className="btn btn-secondary btn-icon" style={{ width: 40, height: 40 }} onClick={onClose} aria-label="Закрыть">✕</button>
      </header>

      <div className="chat-scroll" ref={scrollRef}>
        {messages.map((m) =>
          m.role === "user" ? (
            <div className="bubble bubble-user" key={m.id}>{m.text}</div>
          ) : (
            <BotMessage key={m.id} msg={m} onConfirm={confirm} />
          )
        )}
        {busy && <div className="bubble bubble-bot">…</div>}
      </div>

      {showSuggest && (
        <div className="chat-suggest">
          {SUGGESTIONS.map((s) => (
            <button key={s} className="tag tag-outline" onClick={() => send(s)}>{s}</button>
          ))}
        </div>
      )}

      <div className="chat-input-row">
        <input
          className="input"
          placeholder="Что съели или купили?"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && send()}
        />
        <button className="btn btn-primary" onClick={() => send()} disabled={busy}>→</button>
      </div>
    </div>
  );
}
