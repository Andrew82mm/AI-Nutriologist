/* Marketing showcase — three real app screens rendered side by side as phone
   frames on a branded backdrop, for a single clean README screenshot (open
   with #showcase). Reuses the same shell markup and CSS as App, so it always
   matches the live UI. Not part of the normal navigation. */
import { useEffect } from "react";
import { SCREENS, TABS } from "./App";
import Diary from "./screens/Diary";
import Fridge from "./screens/Fridge";
import Plan from "./screens/Plan";
import { IconChat, IconArrowRight, IconMoon } from "./Icons";

const noop = () => {};

function renderScreen(id) {
  switch (id) {
    case "diary":
      return <Diary reloadKey={0} onOpenChat={noop} onOpenFridge={noop} onChanged={noop} />;
    case "fridge":
      return <Fridge reloadKey={0} onChanged={noop} />;
    case "plan":
      return <Plan />;
    default:
      return null;
  }
}

/* One phone: the App shell (header + screen + assistant bar + tabs) frozen on a
   given screen. Static — no theme toggle / navigation wiring needed. */
function Phone({ screenId }) {
  const meta = SCREENS[screenId];
  return (
    <div className="app-frame showcase-phone">
      <header className="app-header">
        <div style={{ flex: 1, minWidth: 0 }}>
          <div className="app-kicker">{meta.kicker}</div>
          <div className="app-title">{meta.title}</div>
        </div>
        <span className="btn btn-secondary btn-icon" style={{ width: 40, height: 40, flex: "none" }}>
          <IconMoon />
        </span>
      </header>

      <main className="app-scroll">{renderScreen(screenId)}</main>

      {screenId !== "profile" && (
        <div className="assistant-bar">
          <span className="assistant-btn">
            <span className="assistant-icon"><IconChat /></span>
            <span className="assistant-placeholder">Съел… · Купил… · Что приготовить?</span>
            <span className="assistant-arrow"><IconArrowRight /></span>
          </span>
        </div>
      )}

      <nav className="app-tabs">
        {TABS.map(([id, label, Icon]) => (
          <span key={id} className={"app-tab" + (screenId === id ? " is-active" : "")}>
            <Icon />
            <span>{label}</span>
          </span>
        ))}
      </nav>
    </div>
  );
}

export default function Showcase() {
  useEffect(() => {
    document.documentElement.setAttribute("data-theme", "light");
    document.documentElement.setAttribute("data-palette", "forest");
  }, []);

  return (
    <div className="showcase" data-theme="light" data-palette="forest">
      <header className="showcase-head">
        <h1 className="showcase-title">AI-Nutriologist</h1>
      </header>
      <div className="showcase-row">
        <Phone screenId="diary" />
        <Phone screenId="fridge" />
        <Phone screenId="plan" />
      </div>
    </div>
  );
}
