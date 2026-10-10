import { Bell, CheckCircle2, ChevronRight, Siren, Volume2, VolumeX, AlertTriangle } from "lucide-react";
import { Empty, PageHero } from "../components/common";
import { SENSOR_META, fmtDateTime, fmtDuration, fmtNumber, uiStatus } from "../lib/format";

export default function Alerts({ ctx }) {
  const { open, recent } = ctx.data.alarms;
  const critical = open.filter((a) => a.severity === "Critical");
  const unacked = open.filter((a) => a.state === "active");
  const code = (id) => ctx.machines.find((m) => m.id === id)?.code || `M${String(id).padStart(2, "0")}`;
  const history = recent.filter((a) => a.state === "cleared").slice(0, 15);

  return (
    <>
      <PageHero icon={Bell} eyebrow="SAFETY & EVENTS" title="Alarm Management"
        text="Debounced alarms with hysteresis. Acknowledgements are stored with who and when, and survive page reloads." />

      <div className="alarm-banner">
        <div className="alarm-copy">
          <div className={`alarm-icon ${critical.length ? "danger" : "good"}`}><Siren size={22} /></div>
          <div>
            <strong>{critical.length ? `${critical.length} critical alarm${critical.length > 1 ? "s" : ""} active` : "No critical alarms"}</strong>
            <span>{unacked.length ? `${unacked.length} awaiting acknowledgement` : "Everything active has been acknowledged."}</span>
          </div>
        </div>
        <div className="alarm-actions">
          <button className={`sound-toggle ${ctx.soundEnabled ? "on" : ""}`} onClick={ctx.soundEnabled ? ctx.disableAlarm : ctx.enableAlarm}>
            {ctx.soundEnabled ? <Volume2 size={17} /> : <VolumeX size={17} />} {ctx.soundEnabled ? "Siren Armed" : "Enable Siren"}
          </button>
          {unacked.length > 0 && <button className="ack-btn" onClick={ctx.ackAll}><Bell size={16} /> Acknowledge all</button>}
        </div>
      </div>

      <section className="alerts-table-panel">
        <div className="panel-heading"><div><span className="small-label">ACTIVE</span><h3>Open alarms</h3></div><span className="alert-counter">{open.length}</span></div>
        {open.length === 0 ? <Empty icon={CheckCircle2} title="All systems normal" text="No open alarms." /> : open.map((a) => (
          <div className={`event-row ${a.severity === "Critical" ? "critical" : "warning"}`} key={a.id}>
            <div className="event-severity"><AlertTriangle size={17} /></div>
            <div>
              <strong>{code(a.machine_id)} · {SENSOR_META[a.sensor_type]?.name || a.sensor_type}</strong>
              <span>{a.message} · since {fmtDateTime(a.raised_at)} ({fmtDuration(a.duration_seconds)}){a.peak_value !== null && a.sensor_type !== "connectivity" ? ` · peak ${fmtNumber(a.peak_value)}` : ""}</span>
            </div>
            <b>{a.severity.toUpperCase()}{a.max_severity !== a.severity ? ` (was ${a.max_severity})` : ""}</b>
            {a.state === "active"
              ? <button className="ack-btn small" onClick={() => ctx.ack(a.id)}>Acknowledge</button>
              : <span className="acked">✓ {a.acknowledged_by}</span>}
            <ChevronRight size={15} />
          </div>
        ))}
      </section>

      <section className="alerts-table-panel">
        <div className="panel-heading"><div><span className="small-label">LOG</span><h3>Recently cleared</h3></div><span className="alert-counter">{history.length}</span></div>
        {history.length === 0 ? <Empty icon={CheckCircle2} title="No cleared alarms yet" text="History appears here as alarms resolve." /> : history.map((a) => (
          <div className={`event-row ${uiStatus("Normal")} cleared`} key={a.id}>
            <div className="event-severity"><CheckCircle2 size={17} /></div>
            <div>
              <strong>{code(a.machine_id)} · {SENSOR_META[a.sensor_type]?.name || a.sensor_type} <em>({a.max_severity})</em></strong>
              <span>{fmtDateTime(a.raised_at)} → {fmtDateTime(a.cleared_at)} · lasted {fmtDuration(a.duration_seconds)}{a.acknowledged_by ? ` · ack by ${a.acknowledged_by}` : " · never acknowledged"}</span>
            </div>
            <b>CLEARED</b>
          </div>
        ))}
      </section>
    </>
  );
}
