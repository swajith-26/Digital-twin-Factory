import { AlertTriangle, ArrowDownRight, ArrowUpRight, ClipboardCheck, Cpu } from "lucide-react";
import { SENSORS, SENSOR_META, fmtDuration, fmtNumber, healthClass, uiStatus } from "../lib/format";
import { StatusBadge } from "./common";

function Trend({ info }) {
  if (!info || info.confidence < 0.55 || Math.abs(info.trend_per_min) < 0.05) return <span className="trend steady">steady</span>;
  const up = info.trend_per_min > 0;
  const Arrow = up ? ArrowUpRight : ArrowDownRight;
  return <span className={`trend ${up ? "up" : "down"}`}><Arrow size={12} />{fmtNumber(Math.abs(info.trend_per_min), 2)}/min</span>;
}

export default function MachineDetail({ machine, ctx }) {
  if (!machine) {
    return <div className="machine-detail"><div className="maintenance-note"><Cpu size={17} /><div><strong>No machine selected</strong><span>Waiting for data from the factory.</span></div></div></div>;
  }

  const health = machine.health;
  const topActions = machine.recommendations.slice(0, 2);

  return (
    <div className="machine-detail">
      <div className="panel-top">
        <div>
          <span className="small-label">{machine.type || "ASSET"} · {machine.zone || "—"}</span>
          <h3>{machine.code} · {machine.name}</h3>
        </div>
        <StatusBadge status={machine.status} />
      </div>

      <div className="detail-main">
        <div className="big-value">{health ?? "--"}<small>% health</small></div>
        <div className="health-line"><span>Computed from limits, trends and anomalies</span><strong>{health !== null ? `${health}%` : "--"}</strong></div>
        <div className="health-track"><span className={healthClass(health)} style={{ width: `${health ?? 0}%` }} /></div>
      </div>

      <div className="sensor-rows">
        {SENSORS.map((sensor) => {
          const info = machine.sensors[sensor];
          const meta = SENSOR_META[sensor];
          const Icon = meta.icon;
          if (!info) return null;
          return (
            <div className={`sensor-row ${uiStatus(info.status)}`} key={sensor}>
              <div className="sensor-icon"><Icon size={15} /></div>
              <div className="sensor-row-name">
                <strong>{meta.name}</strong>
                <Trend info={info} />
              </div>
              <div className="sensor-row-value">{fmtNumber(info.value)}<small>{info.unit}</small></div>
              {info.prediction && (
                <span className={`predict-chip ${info.prediction.level.toLowerCase()}`} title="Statistical trend forecast">
                  {info.prediction.level} in ~{Math.max(1, Math.round(info.prediction.minutes))} min
                </span>
              )}
              {!info.prediction && info.anomaly && <span className="predict-chip anomaly">unusual</span>}
            </div>
          );
        })}
      </div>

      <div className="detail-meta">
        <div><span>Last reading</span><strong>{machine.age_seconds === null ? "--" : `${fmtDuration(machine.age_seconds)} ago`}</strong></div>
        <div><span>Device link</span><strong>{machine.device.state}</strong></div>
        <div><span>Availability (24 h)</span><strong>{machine.availability_24h === null || machine.availability_24h === undefined ? "--" : `${machine.availability_24h}%`}</strong></div>
        <div><span>Open alarms</span><strong>{machine.alarms.length}</strong></div>
      </div>

      {topActions.map((action) => (
        <div className={`maintenance-note ${action.priority}`} key={action.text}>
          <AlertTriangle size={17} />
          <div>
            <strong>{action.priority.toUpperCase()} · recommended action</strong>
            <span>{action.text}</span>
            <button className="ghost-btn tiny" onClick={() => ctx.draftWorkOrder(machine, action)}>
              <ClipboardCheck size={13} /> Create work order
            </button>
          </div>
        </div>
      ))}
    </div>
  );
}
