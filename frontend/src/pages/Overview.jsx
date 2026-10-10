import { lazy, Suspense, useState } from "react";
import { CheckCircle2, ChevronRight, Cpu, Database, Radio, ShieldCheck, Activity, LayoutDashboard, Zap, AlertTriangle, Server } from "lucide-react";
import { ErrorBoundary, SectionTitle } from "../components/common";
import { TrendChart } from "../components/Charts";
import MachineDetail from "../components/MachineDetail";
import { SENSORS, SENSOR_META, STATUS_LABEL, fmtNumber, fmtTime, healthClass, uiStatus } from "../lib/format";

const FactoryScene = lazy(() => import("../components/Factory3D"));

export function Scene3D({ ctx, detailed = false }) {
  return (
    <ErrorBoundary label="The 3D view" hint="Your browser/GPU may not support WebGL. All data is still available in the other pages.">
      <Suspense fallback={<div className="scene-wrap loading-scene">Loading 3D factory...</div>}>
        <FactoryScene machines={ctx.machines} selectedMachine={ctx.selectedId} setSelectedMachine={ctx.setSelectedId} detailed={detailed} />
      </Suspense>
    </ErrorBoundary>
  );
}

export function AlertsPanel({ ctx, limit = 6 }) {
  const open = ctx.data.alarms.open.slice(0, limit);
  const machineName = (id) => ctx.machines.find((m) => m.id === id)?.code || `M${String(id).padStart(2, "0")}`;
  return (
    <div className="alerts-panel">
      <div className="panel-heading">
        <div><span className="small-label">SAFETY MONITOR</span><h3>Active Alarms</h3></div>
        <span className="alert-counter">{ctx.data.alarms.open.length}</span>
      </div>
      <div className="alerts-scroll">
        {open.length === 0 ? (
          <div className="all-clear"><CheckCircle2 size={28} /><strong>All systems normal</strong><span>No active alarms.</span></div>
        ) : open.map((alarm) => (
          <div className={`alert-row ${uiStatus(alarm.severity === "Critical" ? "Critical" : "Warning")}`} key={alarm.id}>
            <div className="alert-symbol"><AlertTriangle size={16} /></div>
            <div>
              <strong>{machineName(alarm.machine_id)} · {SENSOR_META[alarm.sensor_type]?.name || alarm.sensor_type}</strong>
              <span>{alarm.state === "acknowledged" ? `ack by ${alarm.acknowledged_by}` : "needs acknowledgement"} · {fmtTime(alarm.raised_at)}</span>
            </div>
            {alarm.state === "active"
              ? <button className="ghost-btn tiny" onClick={() => ctx.ack(alarm.id)}>ACK</button>
              : <b>{alarm.severity.toUpperCase()}</b>}
          </div>
        ))}
      </div>
    </div>
  );
}

export function Architecture({ ctx }) {
  const { factory, system } = ctx.data;
  const sub = system.subscriber;
  const stages = [
    [Zap, "Edge devices", `${factory.machines_online}/${factory.machines_total} online`, factory.machines_online > 0],
    [Radio, "MQTT broker", sub.details?.mqtt_connected ? "subscriber connected" : "not connected", !!sub.details?.mqtt_connected],
    [Cpu, "Ingestion service", sub.alive ? `${sub.details?.stored_messages ?? 0} msgs stored` : "not running", sub.alive],
    [Database, "PostgreSQL", system.database === "ok" ? "connected" : "error", system.database === "ok"],
    [Server, "FastAPI", ctx.link === "live" ? "streaming (SSE)" : ctx.link, ctx.link === "live" || ctx.link === "polling"],
    [LayoutDashboard, "React twin UI", "this page", true],
  ];
  return (
    <div className="pipeline">
      {stages.map(([Icon, title, sub2, ok], i) => (
        <div className="pipeline-item" key={title}>
          <div className="pipeline-icon"><Icon size={21} /></div>
          <div><strong>{title}</strong><span className={ok ? "good-text" : "bad-text"}>● {sub2}</span></div>
          {i < stages.length - 1 && <ChevronRight className="pipeline-arrow" size={20} />}
        </div>
      ))}
    </div>
  );
}

export default function Overview({ ctx }) {
  const { data, machines, selected, selectedId, setSelectedId } = ctx;
  const [sensor, setSensor] = useState("temperature");
  const factory = data.factory;
  const ui = uiStatus(factory.status);
  const healthy = machines.filter((m) => m.status === "Normal").length;

  return (
    <>
      <section className="hero-grid">
        <div className="hero-copy">
          <div className="hero-kicker"><span className="pulse" /> REAL-TIME MONITORING</div>
          <h2>Virtual Factory<br /><em>Digital Twin</em></h2>
          <p>Live machine telemetry, alarm management and condition-based failure prediction, streamed from the shop floor.</p>
          <div className="hero-stats">
            <div><strong>{String(factory.machines_total).padStart(2, "0")}</strong><span>Machines</span></div>
            <div><strong>{String(healthy).padStart(2, "0")}</strong><span>Healthy</span></div>
            <div><strong>{String(factory.active_alarms).padStart(2, "0")}</strong><span>Active Alarms</span></div>
          </div>
        </div>
        <div className={`overall-badge ${ui}`}>
          <div className="badge-ring"><ShieldCheck size={27} /></div>
          <div><span>FACTORY HEALTH{factory.health !== null ? ` · ${factory.health}%` : ""}</span><strong>{STATUS_LABEL[ui]}</strong></div>
        </div>
      </section>

      <SectionTitle number="01" title="3D Digital Factory" sub="Machines tremble with their real vibration and glow with their real temperature">
        <div className="legend"><span><i className="dot healthy" />Healthy</span><span><i className="dot warning" />Warning</span><span><i className="dot critical" />Critical</span><span><i className="dot offline" />Offline</span></div>
      </SectionTitle>
      <section className="factory-layout">
        <div className="factory-panel"><Scene3D ctx={ctx} /></div>
        <MachineDetail machine={selected} ctx={ctx} />
      </section>

      <SectionTitle number="02" title="Live Machine Telemetry" sub="Health index and key readings of every machine" />
      <section className="telemetry-grid">
        {machines.map((m) => {
          const cls = uiStatus(m.status);
          const t = m.sensors.temperature;
          const v = m.sensors.vibration;
          return (
            <button key={m.id} className={`telemetry-card ${cls} ${selectedId === m.id ? "selected" : ""}`} onClick={() => setSelectedId(m.id)}>
              <div className="telemetry-head"><div className="sensor-icon"><Activity size={19} /></div><span>{m.code}</span><i className={`dot ${cls}`} /></div>
              <div className="telemetry-name">{m.name}</div>
              <div className={`telemetry-value health-${healthClass(m.health)}`}>{m.health ?? "--"}<small>% health</small></div>
              <div className="telemetry-foot"><span>{STATUS_LABEL[cls]}</span><span>{t ? `${fmtNumber(t.value, 1)}° · ${v ? fmtNumber(v.value, 1) : "--"} vib` : "no data"}</span></div>
            </button>
          );
        })}
      </section>

      <section className="analytics-layout">
        <div className="analytics-panel">
          <div className="panel-heading">
            <div><span className="small-label">TREND ANALYSIS · LAST 10 MIN</span><h3>{selected ? `${selected.code} ${SENSOR_META[sensor].name}` : "Trend"}</h3></div>
            <div className="range-picker">
              {SENSORS.map((s) => <button key={s} className={sensor === s ? "active" : ""} onClick={() => setSensor(s)}>{SENSOR_META[s].name}</button>)}
            </div>
          </div>
          {selected && <TrendChart machineId={selected.id} sensor={sensor} minutes={10} />}
        </div>
        <AlertsPanel ctx={ctx} />
      </section>

      <SectionTitle number="03" title="System Architecture" sub="Live status of every stage of the data pipeline" />
      <Architecture ctx={ctx} />
    </>
  );
}
