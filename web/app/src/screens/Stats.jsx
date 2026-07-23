import { useEffect, useState } from "react";
import { api } from "../api";

// Palette (with hard fallbacks so cards render even if a CSS var is missing).
const C_B = "var(--mc-b, #4c9f70)";
const C_ZH = "var(--mc-zh, #e0a458)";
const C_U = "var(--mc-u, #6a89cc)";
const C_ACCENT = "var(--color-accent, #4c9f70)";
const C_DIV = "var(--color-divider, #e5e5e5)";
const C_WARN = "var(--color-danger, #c0392b)";

// Adherence buckets for the heatmap / trend colouring, by kcal/goal ratio.
function ratioColor(logged, ratio) {
  if (!logged) return C_DIV;
  if (ratio < 0.5) return "color-mix(in srgb, " + C_ACCENT + " 25%, transparent)";
  if (ratio < 0.85) return "color-mix(in srgb, " + C_ACCENT + " 55%, transparent)";
  if (ratio <= 1.1) return C_ACCENT;
  return C_WARN;
}

const shortDate = (iso) => iso.slice(8, 10) + "." + iso.slice(5, 7);

// Weekday of an ISO date with Monday = 0 … Sunday = 6 (GitHub-style rows).
const WEEKDAYS = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"];
const dowMon = (iso) => (new Date(iso + "T00:00:00").getDay() + 6) % 7;

// The heatmap shows a fixed trailing window (independent of the 7/30 toggle,
// which only drives the numeric cards below) so it always fills the card.
const HEATMAP_DAYS = 70;

function Card({ title, children, right }) {
  return (
    <div className="card elev-sm" style={{ padding: 14, marginTop: 12 }}>
      <div style={{ display: "flex", alignItems: "center", marginBottom: 10 }}>
        <span className="section-head" style={{ margin: 0, flex: 1 }}>{title}</span>
        {right}
      </div>
      {children}
    </div>
  );
}

// GitHub-style calendar: weeks are columns, weekdays are rows (Пн…Вс). Days
// are coloured by kcal-vs-goal ratio; clicking one opens that day's meals. The
// grid stretches to fill the card width — columns/rows are 1fr and the grid's
// aspect-ratio keeps every cell square regardless of how many weeks it spans.
function CalendarHeatmap({ series, selected, onPick }) {
  const GAP = 4;
  const pad = series.length ? dowMon(series[0].date) : 0;
  const cells = [...Array(pad).fill(null), ...series];
  const weeks = Math.max(1, Math.ceil(cells.length / 7));
  return (
    <div style={{ display: "flex", gap: 6, alignItems: "stretch" }}>
      <div style={{ display: "grid", gridTemplateRows: "repeat(7, 1fr)", gap: GAP, fontSize: 9, opacity: 0.5 }}>
        {WEEKDAYS.map((w, i) => (
          <span key={i} style={{ alignSelf: "center", visibility: i % 2 ? "hidden" : "visible" }}>{w}</span>
        ))}
      </div>
      <div
        style={{
          flex: 1,
          display: "grid",
          gridTemplateColumns: `repeat(${weeks}, 1fr)`,
          gridTemplateRows: "repeat(7, 1fr)",
          gridAutoFlow: "column",
          gap: GAP,
          aspectRatio: `${weeks} / 7`,
        }}
      >
        {cells.map((s, i) =>
          s === null ? (
            <span key={i} />
          ) : (
            <button
              key={i}
              title={`${s.date}: ${s.logged ? s.kcal + " ккал" : "нет записей"}`}
              onClick={() => onPick(s.date)}
              style={{
                width: "100%", height: "100%", borderRadius: 3, padding: 0, cursor: "pointer",
                background: ratioColor(s.logged, s.ratio),
                border: selected === s.date ? "1.5px solid var(--color-text)" : "1px solid transparent",
              }}
            />
          )
        )}
      </div>
    </div>
  );
}

function HeatmapLegend() {
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 6, marginTop: 10, fontSize: 11, opacity: 0.7 }}>
      <span>мало</span>
      {[0.4, 0.7, 1.0, 1.3].map((r) => (
        <span key={r} style={{ width: 12, height: 12, borderRadius: 3, background: ratioColor(true, r) }} />
      ))}
      <span>перебор</span>
    </div>
  );
}

// Read-only meals for the day a user tapped in the heatmap.
function DayDetail({ date }) {
  const [day, setDay] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    setDay(null);
    setError(null);
    api.getDiaryFor(date).then(setDay).catch((e) => setError(e.message));
  }, [date]);

  const head = (
    <div style={{ fontWeight: 700, fontSize: 13, marginBottom: 8 }}>
      {shortDate(date)} · {day ? Math.round(day.consumed.kcal) + " / " + Math.round(day.goal.kcal) + " ккал" : ""}
    </div>
  );

  return (
    <div style={{ marginTop: 12, paddingTop: 12, borderTop: "1px solid " + C_DIV }}>
      {head}
      {error && <div className="state-msg">Ошибка: {error}</div>}
      {!error && !day && <div className="state-msg">Загрузка…</div>}
      {day && day.meals.length === 0 && (
        <div className="state-msg" style={{ padding: "6px 0" }}>Нет записей за этот день.</div>
      )}
      {day &&
        day.meals.map((m) => (
          <div key={m.id} style={{ marginBottom: 10 }}>
            <div style={{ display: "flex", justifyContent: "space-between", fontSize: 13, fontWeight: 600 }}>
              <span>{m.title}</span>
              <span style={{ opacity: 0.7 }}>{Math.round(m.macros.kcal)} ккал</span>
            </div>
            <div style={{ fontSize: 12, opacity: 0.65, lineHeight: 1.4 }}>
              {m.items.map((i) => i.name).join(" · ") || "—"}
            </div>
          </div>
        ))}
    </div>
  );
}

function Tile({ value, label }) {
  return (
    <div style={{ flex: 1, textAlign: "center", padding: "4px 2px" }}>
      <div style={{ fontSize: 22, fontWeight: 700 }}>{value}</div>
      <div style={{ fontSize: 11, opacity: 0.65, lineHeight: 1.2 }}>{label}</div>
    </div>
  );
}

function MacroBar({ label, p, f, c }) {
  const seg = (w, color) => (w > 0 ? <span style={{ width: w + "%", background: color }} /> : null);
  return (
    <div style={{ marginTop: 8 }}>
      <div style={{ fontSize: 12, opacity: 0.7, marginBottom: 3 }}>{label}</div>
      <div style={{ display: "flex", height: 16, borderRadius: 8, overflow: "hidden", background: C_DIV }}>
        {seg(p, C_B)}{seg(f, C_ZH)}{seg(c, C_U)}
      </div>
    </div>
  );
}

export default function Stats() {
  const [days, setDays] = useState(7);
  const [heat, setHeat] = useState(null); // fixed-window data for the heatmap
  const [data, setData] = useState(null); // toggle-driven data for the cards below
  const [error, setError] = useState(null);
  const [selDate, setSelDate] = useState(null);

  // Heatmap: fixed trailing window, fetched once — the toggle never touches it.
  useEffect(() => {
    api.getStats(HEATMAP_DAYS).then(setHeat).catch((e) => setError(e.message));
  }, []);

  // Numeric cards (adherence / macros / spending): driven by the 7/30 toggle.
  useEffect(() => {
    setData(null);
    api.getStats(days).then(setData).catch((e) => setError(e.message));
  }, [days]);

  if (error) return <div className="state-msg">Ошибка загрузки: {error}</div>;

  const a = data && data.adherence;
  const m = data && data.macros;
  const spendMax = data ? Math.max(1, ...data.spending.by_category.map((c) => c.amount)) : 1;

  const toggle = (
    <div className="seg" style={{ display: "flex" }}>
      {[7, 30].map((d) => (
        <label className="seg-opt" key={d} style={{ justifyContent: "center", padding: "2px 10px" }}>
          <input type="radio" name="statsdays" checked={days === d} onChange={() => setDays(d)} />
          {d} дн.
        </label>
      ))}
    </div>
  );

  return (
    <div>
      <Card
        title="Калории и цель"
        right={heat && <span style={{ fontSize: 12, opacity: 0.6 }}>цель {Math.round(heat.goal.kcal)} ккал</span>}
      >
        {!heat ? (
          <div className="state-msg" style={{ padding: "6px 0" }}>Загрузка…</div>
        ) : (
          <>
            <CalendarHeatmap
              series={heat.series}
              selected={selDate}
              onPick={(d) => setSelDate((cur) => (cur === d ? null : d))}
            />
            <HeatmapLegend />
            {selDate ? (
              <DayDetail date={selDate} />
            ) : (
              <div style={{ marginTop: 10, fontSize: 11, opacity: 0.5 }}>
                Нажми на квадратик дня, чтобы посмотреть, что ты ел.
              </div>
            )}
          </>
        )}
      </Card>

      {/* The 7/30 toggle drives only these lower cards, not the heatmap. */}
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginTop: 18 }}>
        <span className="section-head" style={{ margin: 0 }}>Статистика за период</span>
        {toggle}
      </div>

      {!data ? (
        <div className="state-msg" style={{ padding: "12px 0" }}>Загрузка…</div>
      ) : (
        <>
          <Card title="Приверженность">
            <div style={{ display: "flex" }}>
              <Tile value={a.pct_within + "%"} label="дней в цели" />
              <Tile value={a.streak} label="дней подряд" />
              <Tile value={a.days_logged} label="дней с записями" />
              <Tile value={a.avg_kcal} label="ср. ккал/день" />
            </div>
          </Card>

          <Card title="Баланс БЖУ">
            <MacroBar label={`Факт · Б ${m.protein_pct}% · Ж ${m.fat_pct}% · У ${m.carbs_pct}%`}
              p={m.protein_pct} f={m.fat_pct} c={m.carbs_pct} />
            <MacroBar label={`Цель · Б ${m.goal_protein_pct}% · Ж ${m.goal_fat_pct}% · У ${m.goal_carbs_pct}%`}
              p={m.goal_protein_pct} f={m.goal_fat_pct} c={m.goal_carbs_pct} />
          </Card>

          <Card title="Траты по чекам" right={<span style={{ fontWeight: 700 }}>{data.spending.total} ₽</span>}>
            {data.spending.by_category.length === 0 ? (
              <div className="state-msg" style={{ padding: "6px 0" }}>Нет импортированных чеков за период.</div>
            ) : (
              data.spending.by_category.map((c, i) => (
                <div key={i} style={{ marginTop: 8 }}>
                  <div style={{ display: "flex", justifyContent: "space-between", fontSize: 13, marginBottom: 3 }}>
                    <span>{c.category}</span>
                    <span style={{ opacity: 0.7 }}>{c.amount} ₽</span>
                  </div>
                  <div style={{ height: 8, borderRadius: 4, background: C_DIV }}>
                    <div style={{ width: (c.amount / spendMax) * 100 + "%", height: "100%", borderRadius: 4, background: C_ACCENT }} />
                  </div>
                </div>
              ))
            )}
          </Card>
        </>
      )}
    </div>
  );
}
