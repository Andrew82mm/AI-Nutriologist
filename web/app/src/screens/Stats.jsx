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

function TrendChart({ series, goal }) {
  const W = 320, H = 120, pad = 6;
  const n = series.length;
  const step = (W - pad * 2) / n;
  const bw = Math.max(2, step * 0.62);
  const max = Math.max(goal * 1.2, ...series.map((s) => s.kcal), 1);
  const y = (v) => H - (v / max) * (H - 16);
  const goalY = y(goal);
  return (
    <svg width="100%" viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" style={{ display: "block" }}>
      <line x1="0" x2={W} y1={goalY} y2={goalY} stroke={C_ACCENT} strokeWidth="1"
        strokeDasharray="4 3" opacity="0.7" />
      {series.map((s, i) => {
        const x = pad + i * step + (step - bw) / 2;
        const yy = y(s.kcal);
        return (
          <rect key={i} x={x} y={yy} width={bw} height={Math.max(0, H - yy)} rx="1.5"
            fill={ratioColor(s.logged, s.ratio)}>
            <title>{`${s.date}: ${s.kcal} ккал`}</title>
          </rect>
        );
      })}
    </svg>
  );
}

function Heatmap({ series }) {
  return (
    <>
      <div style={{ display: "flex", flexWrap: "wrap", gap: 4 }}>
        {series.map((s, i) => (
          <div key={i} title={`${s.date}: ${s.logged ? s.kcal + " ккал" : "нет записей"}`}
            style={{ width: 16, height: 16, borderRadius: 4, background: ratioColor(s.logged, s.ratio) }} />
        ))}
      </div>
      <div style={{ display: "flex", alignItems: "center", gap: 6, marginTop: 8, fontSize: 11, opacity: 0.7 }}>
        <span>мало</span>
        <span style={{ width: 12, height: 12, borderRadius: 3, background: ratioColor(true, 0.4) }} />
        <span style={{ width: 12, height: 12, borderRadius: 3, background: ratioColor(true, 0.7) }} />
        <span style={{ width: 12, height: 12, borderRadius: 3, background: ratioColor(true, 1.0) }} />
        <span style={{ width: 12, height: 12, borderRadius: 3, background: ratioColor(true, 1.3) }} />
        <span>перебор</span>
      </div>
    </>
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
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    setData(null);
    setError(null);
    api.getStats(days).then(setData).catch((e) => setError(e.message));
  }, [days]);

  if (error) return <div className="state-msg">Ошибка загрузки: {error}</div>;
  if (!data) return <div className="state-msg">Загрузка…</div>;

  const a = data.adherence;
  const m = data.macros;
  const spendMax = Math.max(1, ...data.spending.by_category.map((c) => c.amount));

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
      <div style={{ display: "flex", justifyContent: "flex-end" }}>{toggle}</div>

      <Card title="Калории по дням">
        <TrendChart series={data.series} goal={data.goal.kcal} />
        <div style={{ display: "flex", justifyContent: "space-between", fontSize: 11, opacity: 0.6, marginTop: 4 }}>
          <span>{shortDate(data.series[0].date)}</span>
          <span>цель {Math.round(data.goal.kcal)} ккал</span>
          <span>{shortDate(data.series[data.series.length - 1].date)}</span>
        </div>
      </Card>

      <Card title="Достижение цели">
        <Heatmap series={data.series} />
      </Card>

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
    </div>
  );
}
