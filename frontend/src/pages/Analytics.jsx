import { useState } from "react";
import { Bar, BarChart, CartesianGrid, Cell, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { Bell, BarChart3, Clock3, Cpu, ShieldCheck, Siren } from "lucide-react";
import { Kpi, PageHero } from "../components/common";
import { RangePicker, TrendChart } from "../components/Charts";
import { SENSORS, SENSOR_META, STATUS_LABEL, fmtDuration, healthClass } from "../lib/format";
import OeeSimulation from "../components/OeeSimulation";

const HEALTH_COLOR = { healthy: "#22c55e", warning: "#f59e0b", critical: "#ef4444", offline: "#64748b" };

export default function Analytics({ ctx }) {
  const [minutes, setMinutes] = useState(10);
  const { factory } = ctx.data;
  const m = ctx.selected;

  const healthData = ctx.machines.map((x) => ({ name: x.code, health: x.health ?? 0, cls: healthClass(x.health) }));
  const forecasts = ctx.machines.flatMap((x) =>
    Object.entries(x.sensors).filter(([, s]) => s.prediction).map(([sensor, s]) => ({ machine: x, sensor, p: s.prediction })));

  return (
    <>
      <PageHero icon={BarChart3} eyebrow="OPERATIONS ANALYTICS" title="Telemetry Intelligence"
        text="Fleet health, alarm statistics and statistical failure forecasts computed from the live data stream." />
      <div className="kpi-grid">
        <Kpi label="Fleet health" value={factory.health === null ? "--" : `${factory.health}%`} icon={ShieldCheck} tone={factory.health !== null && factory.health < 70 ? "danger" : "good"} />
        <Kpi label="Machines online" value={`${factory.machines_online}/${factory.machines_total}`} icon={Cpu} tone={factory.machines_offline ? "danger" : "good"} />
        <Kpi label="Active alarms" value={factory.active_alarms} icon={Bell} tone={factory.active_alarms ? "danger" : "good"} />
        <Kpi label="Critical now" value={factory.critical_alarms} icon={Siren} tone={factory.critical_alarms ? "danger" : "good"} />
        <Kpi label="Alarms raised (24 h)" value={factory.raised_24h} icon={Bell} />
        <Kpi label="Mean time to acknowledge" value={fmtDuration(factory.mean_time_to_acknowledge_seconds)} icon={Clock3} />
      </div>


      <OeeSimulation />

      <div className="analytics-layout">
        <div className="analytics-panel">
          <div className="panel-heading"><div><span className="small-label">FLEET COMPARISON</span><h3>Machine health index</h3></div></div>
          <ResponsiveContainer width="100%" height={230}>
            <BarChart data={healthData} margin={{ top: 8, right: 14, left: -18, bottom: 0 }}>
              <CartesianGrid stroke="#1b3046" strokeDasharray="3 4" />
              <XAxis dataKey="name" stroke="#60758b" tick={{ fontSize: 11 }} />
              <YAxis domain={[0, 100]} stroke="#60758b" tick={{ fontSize: 10 }} />
              <Tooltip cursor={{ fill: "#0d1d2e" }} contentStyle={{ background: "#0b1728", border: "1px solid #24405c", borderRadius: 8, color: "#e5edf5" }} />
              <Bar dataKey="health" radius={[6, 6, 0, 0]} isAnimationActive={false}>
                {healthData.map((d) => <Cell key={d.name} fill={HEALTH_COLOR[d.cls]} />)}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>
        <div className="alerts-panel">
          <div className="panel-heading"><div><span className="small-label">PREDICTIVE MAINTENANCE</span><h3>Failure forecasts</h3></div><span className="alert-counter">{forecasts.length}</span></div>
          <div className="alerts-scroll">
            {forecasts.length === 0 ? (
              <div className="all-clear"><ShieldCheck size={28} /><strong>No trends heading for a limit</strong><span>Forecast = least-squares trend of the last 3 min, shown only when the fit is strong and a limit would be crossed within 30 min.</span></div>
            ) : forecasts.map(({ machine, sensor, p }) => (
              <div className={`alert-row ${p.level === "Critical" ? "critical" : "warning"}`} key={`${machine.id}-${sensor}`}>
                <div className="alert-symbol"><Clock3 size={16} /></div>
                <div><strong>{machine.code} · {SENSOR_META[sensor].name}</strong><span>reaches {p.level.toLowerCase()} limit {p.limit} in ~{Math.max(1, Math.round(p.minutes))} min</span></div>
                <b>{STATUS_LABEL[p.level === "Critical" ? "critical" : "warning"]}</b>
              </div>
            ))}
          </div>
        </div>
      </div>

      <div className="panel-heading page-subhead">
        <div><span className="small-label">{m?.code} · {m?.name}</span><h3>Sensor trends</h3></div>
        <RangePicker value={minutes} onChange={setMinutes} />
      </div>
      <div className="analytics-page-grid">
        {m && SENSORS.map((s) => (
          <div className="analytics-panel" key={s}>
            <div className="panel-heading"><div><span className="small-label">{m.code}</span><h3>{SENSOR_META[s].name} trend</h3></div></div>
            <TrendChart machineId={m.id} sensor={s} minutes={minutes} height={220} />
          </div>
        ))}
      </div>
    </>
  );
}
