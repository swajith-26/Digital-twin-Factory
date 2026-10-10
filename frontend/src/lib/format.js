import { Activity, Gauge, Thermometer, Wind } from "lucide-react";

export const SENSORS = ["temperature", "humidity", "vibration", "pressure"];

export const SENSOR_META = {
  temperature: { name: "Temperature", icon: Thermometer, color: "#22d3ee" },
  humidity: { name: "Humidity", icon: Wind, color: "#38bdf8" },
  vibration: { name: "Vibration", icon: Activity, color: "#a78bfa" },
  pressure: { name: "Pressure", icon: Gauge, color: "#14b8a6" },
  connectivity: { name: "Connectivity", icon: Activity, color: "#94a3b8" },
};

// Backend status -> the CSS class used throughout the design.
const UI_STATUS = { Normal: "healthy", Warning: "warning", Critical: "critical", Offline: "offline", "No Data": "offline" };
export const uiStatus = (status) => UI_STATUS[status] || "offline";
export const STATUS_LABEL = { healthy: "HEALTHY", warning: "WARNING", critical: "CRITICAL", offline: "OFFLINE" };

export const fmtNumber = (value, digits = 2) =>
  Number.isFinite(Number(value)) && value !== null ? Number(value).toFixed(digits) : "--";

export const fmtTime = (iso) => (iso ? new Date(iso).toLocaleTimeString() : "--");
export const fmtDateTime = (iso) => (iso ? new Date(iso).toLocaleString() : "--");

export function fmtDuration(seconds) {
  if (seconds === null || seconds === undefined) return "--";
  const s = Math.max(0, Math.round(seconds));
  if (s < 60) return `${s}s`;
  if (s < 3600) return `${Math.floor(s / 60)}m ${String(s % 60).padStart(2, "0")}s`;
  return `${Math.floor(s / 3600)}h ${String(Math.floor((s % 3600) / 60)).padStart(2, "0")}m`;
}

export const healthClass = (health) => (health === null || health === undefined ? "offline" : health < 40 ? "critical" : health < 70 ? "warning" : "healthy");
