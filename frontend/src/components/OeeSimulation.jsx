import { useMemo, useState } from "react";
import { Activity, CirclePause, CirclePlay, Factory, RotateCcw, ShieldCheck } from "lucide-react";

// Clearly labelled demo-only production counters. Replace this component's
// data source with PLC counters when genuine production data is available.
const INITIAL = {
  plannedMinutes: 480,
  runMinutes: 432,
  total: 500,
  good: 485,
  idealCycleSeconds: 45,
};

function clamp(value, min, max) {
  return Math.min(max, Math.max(min, value));
}

export default function OeeSimulation() {
  const [data, setData] = useState(INITIAL);
  const [running, setRunning] = useState(true);
  const [eventCount, setEventCount] = useState(0);

  const metrics = useMemo(() => {
    const availability = data.plannedMinutes > 0
      ? clamp((data.runMinutes / data.plannedMinutes) * 100, 0, 100)
      : 0;
    const runSeconds = data.runMinutes * 60;
    const performance = runSeconds > 0
      ? clamp(((data.total * data.idealCycleSeconds) / runSeconds) * 100, 0, 100)
      : 0;
    const quality = data.total > 0 ? clamp((data.good / data.total) * 100, 0, 100) : 0;
    const oee = availability * performance * quality / 10000;
    return { availability, performance, quality, oee };
  }, [data]);

  const addProduction = () => {
    setData((current) => ({
      ...current,
      total: current.total + 10,
      good: current.good + 9,
      runMinutes: clamp(current.runMinutes + 1, 0, current.plannedMinutes),
    }));
    setEventCount((n) => n + 1);
    setRunning(true);
  };

  const addDefect = () => {
    setData((current) => ({
      ...current,
      total: current.total + 1,
    }));
    setEventCount((n) => n + 1);
  };

  const recordDowntime = () => {
    setData((current) => ({
      ...current,
      runMinutes: clamp(current.runMinutes - 15, 0, current.plannedMinutes),
    }));
    setRunning(false);
    setEventCount((n) => n + 1);
  };

  const reset = () => {
    setData(INITIAL);
    setRunning(true);
    setEventCount(0);
  };

  const rows = [
    { label: "Availability", value: metrics.availability, note: `${data.runMinutes} / ${data.plannedMinutes} min run time`, color: "availability" },
    { label: "Performance", value: metrics.performance, note: `${data.total} units · ${data.idealCycleSeconds}s ideal cycle`, color: "performance" },
    { label: "Quality", value: metrics.quality, note: `${data.good} good / ${data.total} total units`, color: "quality" },
  ];

  return (
    <section className="oee-panel">
      <div className="oee-heading">
        <div className="oee-title-wrap">
          <div className="oee-icon"><Factory size={19} /></div>
          <div>
            <span className="small-label">PRODUCTION EFFECTIVENESS</span>
            <h3>Overall Equipment Effectiveness (OEE)</h3>
            <p>Demonstration mode · generated production counters, not PLC data</p>
          </div>
        </div>
        <span className="oee-demo-badge"><Activity size={13} /> SIMULATED DATA</span>
      </div>

      <div className="oee-main">
        <div className={`oee-score ${metrics.oee < 60 ? "low" : metrics.oee < 80 ? "mid" : "high"}`}>
          <span>OVERALL OEE</span>
          <strong>{metrics.oee.toFixed(1)}<small>%</small></strong>
          <div className="oee-score-track"><i style={{ width: `${metrics.oee}%` }} /></div>
          <p>{running ? "Production running (simulated)" : "Downtime event recorded (simulated)"}</p>
        </div>
        <div className="oee-metrics">
          {rows.map((row) => (
            <div className="oee-metric" key={row.label}>
              <div className="oee-metric-top"><span>{row.label}</span><strong>{row.value.toFixed(1)}%</strong></div>
              <div className={`oee-bar ${row.color}`}><i style={{ width: `${row.value}%` }} /></div>
              <small>{row.note}</small>
            </div>
          ))}
        </div>
      </div>

      <div className="oee-controls">
        <div className="oee-control-copy">
          <strong><ShieldCheck size={14} /> Try a production event</strong>
          <span>{eventCount} demo event{eventCount === 1 ? "" : "s"} recorded in this page session</span>
        </div>
        <div className="oee-buttons">
          <button type="button" className="oee-button primary" onClick={addProduction}><CirclePlay size={14} /> Produce 10 units</button>
          <button type="button" className="oee-button" onClick={addDefect}>Add 1 reject</button>
          <button type="button" className="oee-button" onClick={recordDowntime}><CirclePause size={14} /> Record downtime</button>
          <button type="button" className="oee-button subtle" onClick={reset}><RotateCcw size={14} /> Reset demo</button>
        </div>
      </div>
      <p className="oee-footnote">
        Formula: OEE = Availability × Performance × Quality. The current values are illustrative only.
        For real OEE, connect PLC/production counters for run state, total output and good output.
      </p>
    </section>
  );
}
