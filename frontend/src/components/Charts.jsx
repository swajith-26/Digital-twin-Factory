import { useEffect, useState } from "react";
import {
  Area, CartesianGrid, ComposedChart, Line, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";
import { apiGet } from "../lib/api";
import { SENSOR_META } from "../lib/format";

const TOOLTIP_STYLE = { background: "#0b1728", border: "1px solid #24405c", borderRadius: 8, color: "#e5edf5" };

/**
 * Live trend of one sensor of one machine, from /api/history (downsampled
 * server-side, so the same component works for 10 minutes or 7 days).
 * Draws the machine's own warning / critical limits (hidden until the data
 * gets near them) and the min-max band of each time bucket.
 */
export function TrendChart({ machineId, sensor, minutes = 10, height = 260 }) {
  const [state, setState] = useState({ points: [], limits: null, unit: "", error: "" });
  const meta = SENSOR_META[sensor];
  const refreshMs = minutes <= 60 ? 3000 : 15000;

  useEffect(() => {
    let cancelled = false;
    let timer = null;
    let controller = null;

    const load = async () => {
      controller = new AbortController();
      try {
        const data = await apiGet(
          `/api/history?machine_id=${machineId}&sensor=${sensor}&minutes=${minutes}&points=120`,
          controller.signal,
        );
        if (!cancelled) setState({ points: data.points, limits: data.limits, unit: data.unit, error: "" });
      } catch (error) {
        if (!cancelled && error.name !== "AbortError") setState((s) => ({ ...s, error: error.message }));
      } finally {
        if (!cancelled) timer = setTimeout(load, refreshMs);
      }
    };

    load();
    return () => {
      cancelled = true;
      clearTimeout(timer);
      if (controller) controller.abort();
    };
  }, [machineId, sensor, minutes, refreshMs]);

  const data = state.points.map((p) => {
    const d = new Date(p.t);
    return {
      time: minutes <= 60
        ? d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" })
        : d.toLocaleString([], { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" }),
      value: p.avg,
      range: [p.min, p.max],
    };
  });

  const limits = state.limits || {};
  const lines = [
    [limits.warning_high, "#f59e0b", "warn"], [limits.warning_low, "#f59e0b", "warn"],
    [limits.critical_high, "#ef4444", "crit"], [limits.critical_low, "#ef4444", "crit"],
  ].filter(([value]) => value !== null && value !== undefined);

  if (!data.length) {
    return (
      <div className="chart-empty" style={{ height }}>
        {state.error ? `Chart unavailable: ${state.error}` : "Waiting for readings..."}
      </div>
    );
  }

  return (
    <ResponsiveContainer width="100%" height={height}>
      <ComposedChart data={data} margin={{ top: 8, right: 18, left: -14, bottom: 0 }}>
        <CartesianGrid stroke="#1b3046" strokeDasharray="3 4" />
        <XAxis dataKey="time" stroke="#60758b" tick={{ fontSize: 10 }} minTickGap={36} />
        <YAxis stroke="#60758b" tick={{ fontSize: 10 }} domain={["auto", "auto"]} />
        <Tooltip
          contentStyle={TOOLTIP_STYLE}
          formatter={(value, name) => (name === "range"
            ? [`${value[0].toFixed(2)} – ${value[1].toFixed(2)} ${state.unit}`, "min – max"]
            : [`${Number(value).toFixed(2)} ${state.unit}`, "average"])}
        />
        {lines.map(([y, color, key]) => (
          <ReferenceLine key={`${key}-${y}`} y={y} stroke={color} strokeDasharray="5 4" ifOverflow="hidden"
            label={{ value: key === "crit" ? "critical" : "warning", fill: color, fontSize: 10, position: "insideTopRight" }} />
        ))}
        <Area type="monotone" dataKey="range" stroke="none" fill={meta.color} fillOpacity={0.13} isAnimationActive={false} />
        <Line type="monotone" dataKey="value" stroke={meta.color} strokeWidth={2.5} dot={false} isAnimationActive={false} />
      </ComposedChart>
    </ResponsiveContainer>
  );
}

export function RangePicker({ value, onChange }) {
  const options = [[10, "10 min"], [60, "1 h"], [1440, "24 h"], [10080, "7 d"]];
  return (
    <div className="range-picker">
      {options.map(([minutes, label]) => (
        <button key={minutes} className={value === minutes ? "active" : ""} onClick={() => onChange(minutes)}>{label}</button>
      ))}
    </div>
  );
}
