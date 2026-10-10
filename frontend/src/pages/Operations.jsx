import { useCallback, useEffect, useMemo, useState } from "react";
import { Activity, AlertTriangle, CheckCircle2, ClipboardList, Clock3, HardHat, RefreshCw, UserCheck, Users, Wrench } from "lucide-react";
import { Empty, PageHero } from "../components/common";
import { apiGet, apiSend } from "../lib/api";
import { fmtDateTime } from "../lib/format";

const STATUS_LABEL = {
  open: "Unassigned", assigned: "Assigned", in_progress: "In progress",
  verification: "Awaiting verification", done: "Completed",
};
const NEXT = { open: "assigned", assigned: "in_progress", in_progress: "verification", verification: "done", done: "open" };
const NEXT_LABEL = { open: "Assign job", assigned: "Start work", in_progress: "Submit for verification", verification: "Verify & close", done: "Reopen" };

export default function Operations({ ctx }) {
  const [orders, setOrders] = useState([]);
  const [technicians, setTechnicians] = useState([]);
  const [loading, setLoading] = useState(true);
  const [busyId, setBusyId] = useState(null);
  const [notes, setNotes] = useState({});
  const [reload, setReload] = useState(0);
  const [filter, setFilter] = useState("active");
  const { notify, operator, machines } = ctx;

  const load = useCallback(async (signal) => {
    setLoading(true);
    try {
      const [jobs, people] = await Promise.all([
        apiGet("/api/maintenance?status=all&limit=200", signal),
        apiGet("/api/technicians", signal),
      ]);
      setOrders(jobs);
      setTechnicians(people);
    } catch (error) {
      if (error.name !== "AbortError") notify(`Could not load operations data: ${error.message}`, true);
    } finally {
      setLoading(false);
    }
  }, [notify]);

  useEffect(() => {
    const controller = new AbortController();
    load(controller.signal);
    return () => controller.abort();
  }, [load, reload]);

  const active = useMemo(() => orders.filter((o) => o.status !== "done"), [orders]);
  const unassigned = active.filter((o) => !o.assigned_to);
  const inProgress = active.filter((o) => o.status === "in_progress");
  const verify = active.filter((o) => o.status === "verification");
  const overdue = active.filter((o) => o.due_at && new Date(o.due_at).getTime() < Date.now());
  const shown = filter === "active" ? active : filter === "unassigned" ? unassigned : filter === "verification" ? verify : orders.filter((o) => o.status === "done");

  const update = async (order, patch, success) => {
    setBusyId(order.id);
    try {
      await apiSend("PATCH", `/api/maintenance/${order.id}`, patch);
      notify(success);
      setReload((n) => n + 1);
      ctx.refresh();
    } catch (error) {
      notify(`Update failed: ${error.message}`, true);
    } finally {
      setBusyId(null);
    }
  };

  const assign = (order, value) => {
    const assigned_to = value ? Number(value) : null;
    update(order, { assigned_to, ...(assigned_to && order.status === "open" ? { status: "assigned" } : {}) }, assigned_to ? "Technician assigned" : "Job unassigned");
  };

  const machineName = (id) => {
    const m = machines.find((item) => item.id === id);
    return m ? `${m.code} · ${m.name}` : `Machine ${id}`;
  };
  const isOverdue = (o) => o.due_at && new Date(o.due_at).getTime() < Date.now() && o.status !== "done";

  return <>
    <PageHero icon={ClipboardList} eyebrow="CONTROL ROOM · WORKFORCE COORDINATION" title="Operator Control Center"
      text="Triage machine faults, assign technicians, track repair progress and verify that equipment is safe to return to service." />

    <div className="ops-banner">
      <div className="ops-banner-icon"><Activity size={22} /></div>
      <div className="ops-banner-copy"><strong>Shift operations overview</strong><span>Operator: {operator || "Operator"} · {active.length} active work order(s) · Live machine condition is available in Machines and Alerts.</span></div>
      <button className="ghost-btn" onClick={() => setReload((n) => n + 1)} disabled={loading}><RefreshCw size={14} /> Refresh queue</button>
    </div>

    <div className="ops-kpis">
      <button className={`ops-kpi ${filter === "active" ? "selected" : ""}`} onClick={() => setFilter("active")}><span><ClipboardList size={17} /> ACTIVE JOBS</span><strong>{active.length}</strong><small>All jobs not yet completed</small></button>
      <button className={`ops-kpi ${filter === "unassigned" ? "selected" : ""}`} onClick={() => setFilter("unassigned")}><span><AlertTriangle size={17} /> NEED ASSIGNMENT</span><strong>{unassigned.length}</strong><small>Operator action required</small></button>
      <button className={`ops-kpi ${filter === "verification" ? "selected" : ""}`} onClick={() => setFilter("verification")}><span><CheckCircle2 size={17} /> VERIFY REPAIR</span><strong>{verify.length}</strong><small>Awaiting operator sign-off</small></button>
      <div className="ops-kpi"><span><Clock3 size={17} /> OVERDUE</span><strong className={overdue.length ? "ops-danger" : ""}>{overdue.length}</strong><small>Past the target completion time</small></div>
    </div>

    <div className="ops-layout">
      <section className="alerts-table-panel ops-queue">
        <div className="panel-heading"><div><span className="small-label">DISPATCH & FOLLOW-UP</span><h3>{filter === "active" ? "Active work queue" : filter === "unassigned" ? "Jobs requiring assignment" : filter === "verification" ? "Repair verification" : "Completed work orders"}</h3></div><span className="alert-counter">{shown.length}</span></div>
        {loading ? <Empty icon={RefreshCw} title="Loading operations queue" text="Fetching technicians and work orders from the factory API." /> : shown.length === 0 ? <Empty icon={CheckCircle2} title="Queue is clear" text="No work orders match this view." /> : shown.map((o) => {
          const technician = technicians.find((t) => t.id === o.assigned_to);
          const overdueJob = isOverdue(o);
          return <article className={`ops-job prio-${o.priority} ${overdueJob ? "overdue" : ""}`} key={o.id}>
            <div className="ops-job-top">
              <div><div className="ops-job-code">WO-{String(o.id).padStart(4, "0")} · {machineName(o.machine_id)}</div><h4>{o.title}</h4></div>
              <span className={`ops-status status-${o.status}`}>{STATUS_LABEL[o.status] || o.status}</span>
            </div>
            <div className="ops-job-meta"><span className={`ops-priority prio-text-${o.priority}`}>{o.priority.toUpperCase()} PRIORITY</span><span>Created by {o.created_by || "Operator"}</span><span>{fmtDateTime(o.created_at)}</span>{o.due_at && <span className={overdueJob ? "ops-danger" : ""}>{overdueJob ? "OVERDUE · " : "Due · "}{fmtDateTime(o.due_at)}</span>}</div>
            {o.note && <p className="ops-job-note">{o.note}</p>}
            <div className="ops-assignment-row">
              <label><span><Users size={13} /> Assigned technician</span><select value={o.assigned_to ?? ""} onChange={(e) => assign(o, e.target.value)} disabled={busyId === o.id || o.status === "done"}><option value="">Unassigned — select technician</option>{technicians.filter((t) => t.active).map((t) => <option value={t.id} key={t.id}>{t.name} · {t.skills}</option>)}</select></label>
              <div className="ops-worker-info">{technician ? <><strong><UserCheck size={14} /> {technician.employee_code} · {technician.shift} shift</strong><small>{technician.active_jobs} active job(s) · {technician.skills}</small></> : <><strong><HardHat size={14} /> Awaiting assignment</strong><small>Assign a suitable technician to start the response.</small></>}</div>
            </div>
            {(o.status === "in_progress" || o.status === "verification") && <div className="ops-repair-notes"><label htmlFor={`repair-${o.id}`}>Technician repair report</label><textarea id={`repair-${o.id}`} rows="2" maxLength="4000" value={notes[o.id] ?? o.repair_notes ?? ""} onChange={(e) => setNotes((prev) => ({ ...prev, [o.id]: e.target.value }))} placeholder="Inspection findings, parts replaced, test results..."/><button className="ghost-btn tiny" onClick={() => update(o, { repair_notes: notes[o.id] ?? o.repair_notes ?? "" }, "Repair report saved")} disabled={busyId === o.id}>Save report</button></div>}
            <div className="ops-job-bottom"><span className="ops-next-hint"><Wrench size={13} /> {o.status === "verification" ? "Operator: verify the repair before closing." : o.status === "done" ? `Closed ${fmtDateTime(o.closed_at)}` : o.status === "in_progress" ? "Technician should record findings before submitting." : o.status === "assigned" ? "Technician can now start work." : "Assign a technician, then progress the job."}</span><button className={o.status === "verification" ? "ack-btn" : "ghost-btn"} disabled={busyId === o.id || (o.status === "open" && !o.assigned_to) || (o.status === "assigned" && !o.assigned_to)} onClick={() => update(o, { status: NEXT[o.status] }, o.status === "verification" ? "Work order verified and closed" : `Work order moved to ${STATUS_LABEL[NEXT[o.status]]}`)}>{busyId === o.id ? "Saving..." : NEXT_LABEL[o.status] || "Update"}</button></div>
          </article>;
        })}
      </section>

      <aside className="alerts-table-panel ops-team">
        <div className="panel-heading"><div><span className="small-label">WORKFORCE</span><h3>Technician roster</h3></div><span className="alert-counter">{technicians.length}</span></div>
        <p className="ops-side-intro">Demo roster for dispatching jobs by skill and workload. Replace these sample workers with your real team later.</p>
        {technicians.map((t) => <div className="ops-tech" key={t.id}><div className="ops-tech-avatar"><HardHat size={17} /></div><div className="ops-tech-main"><strong>{t.name}</strong><span>{t.employee_code} · {t.shift} shift</span><small>{t.skills}</small></div><div className={`ops-load ${t.active_jobs >= 3 ? "busy" : ""}`}><strong>{t.active_jobs}</strong><span>active</span></div></div>)}
        <div className="ops-rule"><strong>Dispatch guideline</strong><span>Match the fault type to technician skills. Urgent jobs should be assigned first; the operator verifies the repair before closing the job.</span></div>
      </aside>
    </div>
  </>;
}
