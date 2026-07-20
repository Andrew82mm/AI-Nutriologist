import { useEffect, useState } from "react";
import Diary from "./screens/Diary";
import Fridge from "./screens/Fridge";
import Plan from "./screens/Plan";
import Profile from "./screens/Profile";
import Chat from "./Chat";
import {
  IconDiary, IconFridge, IconPlan, IconProfile,
  IconChat, IconArrowRight, IconSun, IconMoon,
} from "./Icons";

const SCREENS = {
  diary: { kicker: "12 июня · сегодня", title: "Дневник" },
  fridge: { kicker: "Инвентарь", title: "Холодильник" },
  plan: { kicker: "Меню и покупки", title: "План" },
  profile: { kicker: "Настройки", title: "Профиль" },
};

const TABS = [
  ["diary", "Дневник", IconDiary],
  ["fridge", "Холодильник", IconFridge],
  ["plan", "План", IconPlan],
  ["profile", "Профиль", IconProfile],
];

export default function App() {
  const [screen, setScreen] = useState("diary");
  const [theme, setTheme] = useState("light");
  const [chatOpen, setChatOpen] = useState(false);
  // Bumped after the chat commits a meal/purchase, so data screens refetch.
  const [reloadKey, setReloadKey] = useState(0);

  useEffect(() => {
    document.documentElement.setAttribute("data-theme", theme);
  }, [theme]);

  const active = SCREENS[screen];

  const renderScreen = () => {
    switch (screen) {
      case "diary": return (
        <Diary
          reloadKey={reloadKey}
          onOpenChat={() => setChatOpen(true)}
          onOpenFridge={() => setScreen("fridge")}
          onChanged={() => setReloadKey((k) => k + 1)}
        />
      );
      case "fridge": return <Fridge reloadKey={reloadKey} />;
      case "plan": return <Plan />;
      case "profile": return <Profile />;
      default: return null;
    }
  };

  return (
    <div className="app-ground" data-theme={theme}>
      <div className="app-frame">
        <header className="app-header">
          <div style={{ flex: 1, minWidth: 0 }}>
            <div className="app-kicker">{active.kicker}</div>
            <div className="app-title">{active.title}</div>
          </div>
          <button
            className="btn btn-secondary btn-icon"
            style={{ width: 40, height: 40, flex: "none" }}
            aria-label="Сменить тему"
            onClick={() => setTheme((t) => (t === "dark" ? "light" : "dark"))}
          >
            {theme === "dark" ? <IconSun /> : <IconMoon />}
          </button>
        </header>

        <main className="app-scroll">{renderScreen()}</main>

        {/* Pinned assistant bar — available everywhere except profile settings. */}
        {screen !== "profile" && (
          <div className="assistant-bar">
            <button className="assistant-btn" onClick={() => setChatOpen(true)}>
              <span className="assistant-icon"><IconChat /></span>
              <span className="assistant-placeholder">Съел… · Купил… · Что приготовить?</span>
              <span className="assistant-arrow"><IconArrowRight /></span>
            </button>
          </div>
        )}

        {chatOpen && (
          <Chat onClose={() => setChatOpen(false)} onCommit={() => setReloadKey((k) => k + 1)} />
        )}

        <nav className="app-tabs">
          {TABS.map(([id, label, Icon]) => (
            <button
              key={id}
              className={"app-tab" + (screen === id ? " is-active" : "")}
              onClick={() => { setScreen(id); setChatOpen(false); }}
            >
              <Icon />
              <span>{label}</span>
            </button>
          ))}
        </nav>
      </div>
    </div>
  );
}
