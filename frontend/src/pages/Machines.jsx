import { useState } from "react";
import { Boxes, Cpu } from "lucide-react";
import { PageHero } from "../components/common";
import { RangePicker, TrendChart } from "../components/Charts";
import MachineDetail from "../components/MachineDetail";
import { SENSORS, SENSOR_META, STATUS_LABEL, fmtNumber, fmtTime, uiStatus } from "../lib/format";

export default function Machines({ ctx }) {
  const [sensor, setSensor] = useState("vibration");
  const [minutes, setMinutes] = useState(10);
  const m = ctx.selected;
  return (
    <>
      <PageHero icon={Boxes} eyebrow="ASSET MANAGEMENT" title="Machine Fleet"
        text="Every production asset with its own sensors, alarm limits and condition forecast." />
      <div className="machine-grid">
        {ctx.machines.map((x) => {
          const cls = uiStatus(x.status);
          return (
            <button key={x.id} className={`machine-card ${cls} ${ctx.selectedId === x.id ? "selected" : ""}`} onClick={() => ctx.setSelectedId(x.id)}>
              <div className="machine-card-head"><div className="sensor-icon"><Cpu size={20} /></div><span className={`status-badge ${cls}`}><i />{STATUS_LABEL[cls]}</span></div>
              <div className="machine-code">{x.code} · {x.type}</div>
              <h3>{x.name}</h3>
              <div className="machine-reading">{x.health ?? "--"}<small>% health</small></div>
              <div className="machine-card-meta"><span>Zone</span><strong>{x.zone || "--"}</strong></div>
              <div className="machine-card-meta"><span>Last reading</span><strong>{fmtTime(x.last_reading_at)}</strong></div>
              <div className="machine-card-meta"><span>Open alarms</span><strong>{x.alarms.length}</strong></div>
            </button>
          );
        })}
      </div>
      <section className="machine-inspector">
        <MachineDetail machine={m} ctx={ctx} />
        <div className="analytics-panel inspector-chart">
          <div className="panel-heading">
            <div><span className="small-label">{m?.code} · SENSOR HISTORY</span><h3>{SENSOR_META[sensor].name}</h3></div>
            <div className="range-picker">
              {SENSORS.map((s) => <button key={s} className={sensor === s ? "active" : ""} onClick={() => setSensor(s)}>{SENSOR_META[s].name}</button>)}
            </div>
          </div>
          <div className="range-row"><RangePicker value={minutes} onChange={setMinutes} /></div>
          {m && <TrendChart machineId={m.id} sensor={sensor} minutes={minutes} height={280} />}
          {m?.sensors[sensor] && (
            <div className="limits-line">
              <span>Alarm limits for {m.code}:</span>
              {["warning_low", "warning_high", "critical_low", "critical_high"].map((k) => {
                const v = m.sensors[sensor].limits[k];
                return v === null || v === undefined ? null : <b key={k} className={k.startsWith("crit") ? "bad-text" : "warn-text"}>{k.replace("_", " ")} {fmtNumber(v, 1)}</b>;
              })}
            </div>
          )}
        </div>
      </section>
    </>
  );
}
