import { useEffect, useState } from "react";
import { History as HistoryIcon, RefreshCw, Search } from "lucide-react";
import { PageHero } from "../components/common";
import { apiGet } from "../lib/api";
import { SENSOR_META, STATUS_LABEL, fmtDateTime, fmtNumber, uiStatus } from "../lib/format";

export default function History({ ctx }) {
  const [rows, setRows] = useState([]);
  const [term, setTerm] = useState("");
  const [machine, setMachine] = useState("all");
  const [nonce, setNonce] = useState(0);
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelled = false;
    let timer = null;
    let controller = null;
    const load = async () => {
      controller = new AbortController();
      try {
        const query = machine === "all" ? "" : `&machine_id=${machine}`;
        const data = await apiGet(`/api/readings?limit=200${query}`, controller.signal);
        if (!cancelled) { setRows(data); setError(""); }
      } catch (e) {
        if (!cancelled && e.name !== "AbortError") setError(e.message);
      } finally {
        if (!cancelled) timer = setTimeout(load, 5000);
      }
    };
    load();
    return () => { cancelled = true; clearTimeout(timer); if (controller) controller.abort(); };
  }, [machine, nonce]);

  const code = (id) => ctx.machines.find((m) => m.id === id)?.code || `M${String(id).padStart(2, "0")}`;
  const shown = rows.filter((r) => `${code(r.machine_id)} ${SENSOR_META[r.sensor_type]?.name || r.sensor_type}`.toLowerCase().includes(term.toLowerCase()));

  return (
    <>
      <PageHero icon={HistoryIcon} eyebrow="HISTORICAL TELEMETRY" title="Reading History"
        text="The newest readings stored in PostgreSQL, each judged against that machine's own alarm limits." />
      <div className="history-tools">
        <div className="search-box"><Search size={16} /><input value={term} onChange={(e) => setTerm(e.target.value)} placeholder="Search machine or sensor..." /></div>
        <select className="machine-filter" value={machine} onChange={(e) => setMachine(e.target.value)}>
          <option value="all">All machines</option>
          {ctx.machines.map((m) => <option key={m.id} value={m.id}>{m.code} · {m.name}</option>)}
        </select>
        <button className="ghost-btn" onClick={() => setNonce((n) => n + 1)}><RefreshCw size={14} /> Refresh</button>
      </div>
      {error && <div className="widget-error"><strong>Could not load readings</strong><span>{error}</span></div>}
      <section className="history-panel">
        <div className="table-head"><span>TIME</span><span>MACHINE</span><span>SENSOR</span><span>VALUE</span><span>STATUS</span></div>
        {shown.map((r) => {
          const cls = uiStatus(r.status);
          return (
            <div className="history-row" key={r.id}>
              <span>{fmtDateTime(r.recorded_at)}</span>
              <strong>{code(r.machine_id)}</strong>
              <span>{SENSOR_META[r.sensor_type]?.name || r.sensor_type}</span>
              <span>{fmtNumber(r.value)} {r.unit}</span>
              <b className={cls}>{STATUS_LABEL[cls]}</b>
            </div>
          );
        })}
      </section>
    </>
  );
}
