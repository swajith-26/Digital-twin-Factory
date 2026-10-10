import { Cpu, Database, Network, Radio, Server, Settings, ShieldCheck } from "lucide-react";
import { PageHero, SectionTitle } from "../components/common";
import { Architecture } from "./Overview";
import { fmtDateTime, fmtDuration, fmtTime } from "../lib/format";

function SystemCard({ icon: Icon, title, status, good, detail }) {
  return (
    <div className="system-card">
      <div className="system-icon"><Icon size={21} /></div>
      <div><span>{title}</span><strong className={good ? "good-text" : "bad-text"}>{status}</strong>{detail && <small className="card-detail">{detail}</small>}</div>
      <i className={good ? "dot healthy" : "dot critical"} />
    </div>
  );
}

export default function System({ ctx }) {
  const { system, factory } = ctx.data;
  const sub = system.subscriber;
  const d = sub.details || {};
  const linkOk = ctx.link === "live" || ctx.link === "polling";

  return (
    <>
      <PageHero icon={Settings} eyebrow="PLATFORM STATUS" title="System & Connectivity"
        text="Every indicator here is measured: service heartbeats, device Last-Will state and stream health." />
      <div className="system-grid">
        <SystemCard icon={Radio} title="MQTT broker" good={!!d.mqtt_connected} status={d.mqtt_connected ? "Connected" : "Not connected"} detail={d.broker} />
        <SystemCard icon={Cpu} title="Ingestion service" good={sub.alive} status={sub.alive ? "Running" : "Not running"}
          detail={sub.alive ? `${d.stored_messages ?? 0} stored · ${d.rejected_messages ?? 0} rejected · heartbeat ${fmtDuration(sub.age_seconds)} ago` : "Start backend/mqtt_subscriber.py"} />
        <SystemCard icon={Database} title="PostgreSQL" good={system.database === "ok"} status={system.database === "ok" ? "Connected" : "Error"} detail={`retention ${system.retention_days ? `${system.retention_days} days` : "unlimited"}`} />
        <SystemCard icon={Server} title="API stream" good={linkOk} status={ctx.link === "live" ? "Live (SSE push)" : ctx.link === "polling" ? "Polling fallback" : "Offline"} detail={`${system.stream_clients ?? 0} dashboard(s) connected`} />
      </div>

      <SectionTitle number="01" title="Edge devices" sub="Connection state reported by each device's MQTT Last Will" />
      <section className="history-panel">
        <div className="table-head"><span>MACHINE</span><span>DEVICE LINK</span><span>LAST REPORT</span><span>LAST READING</span><span>STATUS</span></div>
        {ctx.machines.map((m) => (
          <div className="history-row" key={m.id}>
            <strong>{m.code} · {m.name}</strong>
            <span>{m.device.state}{m.device.updated_at ? ` (${fmtTime(m.device.updated_at)})` : ""}</span>
            <span>{fmtDateTime(m.last_reading_at)}</span>
            <span>{m.age_seconds === null ? "--" : `${fmtDuration(m.age_seconds)} ago`}</span>
            <b className={m.status === "Offline" || m.status === "No Data" ? "offline" : "healthy"}>{m.status.toUpperCase()}</b>
          </div>
        ))}
      </section>

      <section className="architecture architecture-large">
        <SectionTitle number="02" title="Production Data Pipeline" sub="Live path from the shop floor to the digital twin" />
        <Architecture ctx={ctx} />
      </section>
      <div className="system-note">
        <div className="pipeline-icon"><Network size={20} /></div>
        <div><strong>Alarm subsystem</strong><span>Siren: {ctx.soundEnabled ? "armed" : "disabled"} · open alarms: {factory.active_alarms} · unacknowledged: {factory.unacknowledged_alarms} · offline after {system.stale_after_seconds}s of silence</span></div>
      </div>
      <div className="system-note">
        <div className="pipeline-icon"><ShieldCheck size={20} /></div>
        <div><strong>Operator</strong><span>Actions are recorded as "{ctx.operator}". Set your name in the top bar.</span></div>
      </div>
    </>
  );
}
