import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Activity, BarChart3, Bell, Boxes, ChevronRight, ClipboardList, Database, Factory, History, LayoutDashboard, Radio, Settings, User, Wifi, Wrench,
} from "lucide-react";
import { apiSend } from "./lib/api";
import { useFactoryStream } from "./hooks/useFactoryStream";
import Overview from "./pages/Overview";
import FactoryPage from "./pages/Factory";
import Machines from "./pages/Machines";
import Analytics from "./pages/Analytics";
import Alerts from "./pages/Alerts";
import Maintenance from "./pages/Maintenance";
import Operations from "./pages/Operations";
import HistoryPage from "./pages/History";
import System from "./pages/System";
import "./App.css";

const NAV = [
  [LayoutDashboard, "Overview"], [ClipboardList, "Operations"], [Factory, "3D Factory"], [Boxes, "Machines"], [BarChart3, "Analytics"],
  [Bell, "Alerts"], [Wrench, "Maintenance"], [History, "History"], [Settings, "System"],
];

const PAGES = {
  Overview, Operations, "3D Factory": FactoryPage, Machines, Analytics, Alerts, Maintenance, History: HistoryPage, System,
};

function loadOperator() {
  try {
    return localStorage.getItem("dtf.operator") || "Operator";
  } catch {
    return "Operator";
  }
}

function App() {
  const { snapshot, link, error, refresh } = useFactoryStream();
  const [activeNav, setActiveNav] = useState("Overview");
  const [selectedId, setSelectedId] = useState(null);
  const [operator, setOperator] = useState(loadOperator);
  const [soundEnabled, setSoundEnabled] = useState(false);
  const [notice, setNotice] = useState(null);
  const [draft, setDraft] = useState(null);
  const [clock, setClock] = useState(() => new Date());

  const audioRef = useRef(null);
  const soundRef = useRef(false);
  const heardAlarms = useRef(new Set());
  const noticeTimer = useRef(null);

  const machines = useMemo(() => snapshot?.machines ?? [], [snapshot]);
  const selected = machines.find((m) => m.id === selectedId) || machines[0] || null;

  useEffect(() => {
    const timer = setInterval(() => setClock(new Date()), 1000);
    return () => clearInterval(timer);
  }, []);

  useEffect(() => () => clearTimeout(noticeTimer.current), []);

  const notify = useCallback((text, isError = false) => {
    setNotice({ text, isError });
    clearTimeout(noticeTimer.current);
    noticeTimer.current = setTimeout(() => setNotice(null), 4500);
  }, []);

  const changeOperator = (value) => {
    setOperator(value);
    try {
      localStorage.setItem("dtf.operator", value);
    } catch {
      // storage unavailable (private mode) - the name just won't persist
    }
  };

  // -------------------------------------------------------------- siren
  const playAlarm = useCallback((severity = "critical") => {
    if (!soundRef.current) return;
    try {
      const ctx = audioRef.current;
      if (!ctx) return;
      if (ctx.state === "suspended") ctx.resume();
      const now = ctx.currentTime;
      const beeps = severity === "critical" ? 5 : 2;
      for (let i = 0; i < beeps; i++) {
        const osc = ctx.createOscillator();
        const gain = ctx.createGain();
        osc.type = "square";
        osc.frequency.setValueAtTime(severity === "critical" ? 880 : 620, now + i * 0.24);
        gain.gain.setValueAtTime(0.0001, now + i * 0.24);
        gain.gain.exponentialRampToValueAtTime(0.18, now + i * 0.24 + 0.02);
        gain.gain.exponentialRampToValueAtTime(0.0001, now + i * 0.24 + 0.16);
        osc.connect(gain);
        gain.connect(ctx.destination);
        osc.start(now + i * 0.24);
        osc.stop(now + i * 0.24 + 0.18);
      }
    } catch {
      // browser audio unavailable
    }
  }, []);

  const enableAlarm = useCallback(async () => {
    try {
      const AudioCtx = window.AudioContext || window.webkitAudioContext;
      if (!AudioCtx) return;
      if (!audioRef.current) audioRef.current = new AudioCtx();
      if (audioRef.current.state === "suspended") await audioRef.current.resume();
      soundRef.current = true;
      setSoundEnabled(true);
      heardAlarms.current.clear(); // sound any critical alarm that is already open
    } catch {
      soundRef.current = false;
      setSoundEnabled(false);
    }
  }, []);

  const disableAlarm = useCallback(() => {
    soundRef.current = false;
    setSoundEnabled(false);
  }, []);

  // Sound once for every NEW (or newly escalated) critical alarm that is still
  // unacknowledged - acknowledging in the dashboard is stored in the database.
  useEffect(() => {
    if (!snapshot) return;
    const fresh = snapshot.alarms.open.filter(
      (a) => a.severity === "Critical" && a.state === "active" && !heardAlarms.current.has(`${a.id}:${a.max_severity}`),
    );
    if (!soundRef.current) return;
    fresh.forEach((a) => heardAlarms.current.add(`${a.id}:${a.max_severity}`));
    if (fresh.length) playAlarm("critical");
  }, [snapshot, playAlarm]);

  // ------------------------------------------------------------ actions
  const ack = useCallback(async (id) => {
    try {
      await apiSend("POST", `/api/alarms/${id}/ack`, { by: operator });
      refresh();
    } catch (e) {
      notify(`Could not acknowledge: ${e.message}`, true);
    }
  }, [operator, refresh, notify]);

  const ackAll = useCallback(async () => {
    try {
      const result = await apiSend("POST", "/api/alarms/acknowledge-all", { by: operator });
      notify(`${result.acknowledged} alarm(s) acknowledged`);
      refresh();
    } catch (e) {
      notify(`Could not acknowledge: ${e.message}`, true);
    }
  }, [operator, refresh, notify]);

  const draftWorkOrder = useCallback((machine, action) => {
    setDraft({
      machine_id: machine.id,
      title: action.text.slice(0, 90),
      priority: action.priority,
      note: `Raised from live condition monitoring (health ${machine.health ?? "n/a"}%).`,
    });
    setActiveNav("Maintenance");
  }, []);

  const ctx = {
    data: snapshot, machines, selected, selectedId: selected?.id ?? null, setSelectedId,
    link, operator, notify, refresh, ack, ackAll, draftWorkOrder,
    draft, clearDraft: () => setDraft(null),
    soundEnabled, enableAlarm, disableAlarm,
  };

  const sub = snapshot?.system?.subscriber;
  const dbOk = snapshot?.system?.database === "ok";
  const mqttOk = !!sub?.details?.mqtt_connected && sub.alive;
  const live = link === "live" || link === "polling";
  const Page = PAGES[activeNav];

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand"><div className="brand-mark"><Factory size={22} /></div><div><strong>DIGITAL TWIN</strong><span>FACTORY</span></div></div>
        <div className="sidebar-label">CONTROL CENTER</div>
        <nav>
          {NAV.map(([Icon, label]) => (
            <button key={label} className={activeNav === label ? "nav-item active" : "nav-item"} onClick={() => setActiveNav(label)}>
              <Icon size={18} /><span>{label}</span>
              {label === "Alerts" && snapshot?.factory.unacknowledged_alarms > 0 && <em className="nav-badge">{snapshot.factory.unacknowledged_alarms}</em>}
              {activeNav === label && <ChevronRight size={15} className="nav-arrow" />}
            </button>
          ))}
        </nav>
        <div className="sidebar-bottom">
          <div className="connection-card">
            <div className="connection-title"><Radio size={15} /> SYSTEM STATUS</div>
            <div className="connection-row"><span>MQTT Broker</span><b className={mqttOk ? "connected" : "disconnected"}>● {mqttOk ? "Connected" : "Unknown"}</b></div>
            <div className="connection-row"><span>API Service</span><b className={live ? "connected" : "disconnected"}>● {live ? "Connected" : "Offline"}</b></div>
            <div className="connection-row"><span>Database</span><b className={dbOk ? "connected" : "disconnected"}>● {dbOk ? "Connected" : "Unknown"}</b></div>
            <div className="connection-row"><span>Siren</span><b className={soundEnabled ? "connected" : "disconnected"}>● {soundEnabled ? "Armed" : "Disabled"}</b></div>
          </div>
          <div className="version">INDUSTRY 4.0 · v4.0</div>
        </div>
      </aside>

      <main className="main">
        <header className="topbar">
          <div><div className="eyebrow">INDUSTRIAL IoT / DIGITAL TWIN PLATFORM</div><h1>Factory Operations Center</h1></div>
          <div className="topbar-right">
            <label className="operator-box" title="Recorded on acknowledgements and work orders"><User size={14} />
              <input value={operator} onChange={(e) => changeOperator(e.target.value)} maxLength={40} aria-label="Operator name" />
            </label>
            <div className="data-pill"><Database size={15} /> PostgreSQL <span className={dbOk ? "" : "off"}>●</span></div>
            <div className="data-pill"><Wifi size={15} /> MQTT <span className={mqttOk ? "" : "off"}>●</span></div>
            <div className={`live-pill ${live ? "live" : ""}`}><i /> {link === "live" ? "LIVE" : link === "polling" ? "POLLING" : link === "connecting" ? "CONNECTING" : "OFFLINE"}</div>
            <div className="clock">{clock.toLocaleTimeString()}</div>
          </div>
        </header>

        {notice && <div className={`toast ${notice.isError ? "error" : ""}`} role="status">{notice.text}</div>}

        {!snapshot ? (
          <div className="splash">
            <div className="pulse big" />
            <strong>{link === "offline" ? "Cannot reach the factory API" : "Connecting to the factory..."}</strong>
            <span>{error || "Waiting for the first live snapshot."}</span>
          </div>
        ) : (
          <>
            {link === "offline" && <div className="widget-error"><strong>Connection lost</strong><span>{error} Showing the last known data.</span></div>}
            <Page ctx={ctx} />
          </>
        )}

        <footer>Digital Twin Factory · Industrial IoT Control Center · MQTT + PostgreSQL + FastAPI + React Three Fiber · {new Date().getFullYear()}</footer>
      </main>
    </div>
  );
}

export default App;
