import { useEffect, useState } from "react";
import { CheckCircle2, ClipboardCheck, Wrench } from "lucide-react";
import { Empty, PageHero, StatusBadge } from "../components/common";
import { apiGet, apiSend } from "../lib/api";
import { fmtDateTime, healthClass, uiStatus } from "../lib/format";

const NEXT = { open: "assigned", assigned: "in_progress", in_progress: "verification", verification: "done", done: "open" };
const NEXT_LABEL = { open: "Mark assigned", assigned: "Start work", in_progress: "Submit for verification", verification: "Verify & close", done: "Reopen" };

export default function Maintenance({ ctx }) {
  const [orders, setOrders] = useState([]);
  const [reloadKey, setReloadKey] = useState(0);
  // A "Create work order" button elsewhere navigates here with a draft.
  const [form, setForm] = useState(() => ctx.draft
    ? { machine_id: ctx.draft.machine_id, title: ctx.draft.title, priority: ctx.draft.priority, note: ctx.draft.note }
    : { machine_id: ctx.machines[0]?.id || 1, title: "", priority: "medium", note: "" });
  const [busy, setBusy] = useState(false);
  const { notify, draft, clearDraft } = ctx;

  useEffect(() => {
    if (draft) clearDraft();
  }, [draft, clearDraft]);

  useEffect(() => {
    const controller = new AbortController();
    const run = async () => {
      try {
        setOrders(await apiGet("/api/maintenance?status=all", controller.signal));
      } catch (error) {
        if (error.name !== "AbortError") notify(`Could not load work orders: ${error.message}`, true);
      }
    };
    run();
    return () => controller.abort();
  }, [reloadKey, notify]);

  const load = async () => setReloadKey((k) => k + 1);

  const code = (id) => ctx.machines.find((m) => m.id === id)?.code || `M${String(id).padStart(2, "0")}`;

  const submit = async (event) => {
    event.preventDefault();
    setBusy(true);
    try {
      await apiSend("POST", "/api/maintenance", { ...form, machine_id: Number(form.machine_id), created_by: ctx.operator });
      ctx.notify("Work order created");
      setForm((f) => ({ ...f, title: "", note: "" }));
      await load();
    } catch (error) {
      ctx.notify(`Could not create work order: ${error.message}`, true);
    } finally {
      setBusy(false);
    }
  };

  const advance = async (order) => {
    try {
      await apiSend("PATCH", `/api/maintenance/${order.id}`, { status: NEXT[order.status] });
      await load();
    } catch (error) {
      ctx.notify(`Could not update work order: ${error.message}`, true);
    }
  };

  return (
    <>
      <PageHero icon={Wrench} eyebrow="RELIABILITY ENGINEERING" title="Maintenance Center"
        text="Condition-based recommendations from live data, turned into tracked work orders." />

      <div className="maintenance-grid">
        {ctx.machines.map((m) => {
          const cls = uiStatus(m.status);
          const top = m.recommendations[0];
          return (
            <div className={`maintenance-card ${cls}`} key={m.id}>
              <div className="maintenance-head">
                <div><span className="small-label">ASSET</span><h3>{m.code} · {m.name}</h3></div>
                <StatusBadge status={m.status} />
              </div>
              <div className="maintenance-health"><span>Health index</span><strong>{m.health === null ? "--" : `${m.health}%`}</strong></div>
              <div className="health-track"><span className={healthClass(m.health)} style={{ width: `${m.health ?? 0}%` }} /></div>
              <p>{top ? top.text : m.status === "Offline" ? "Machine is offline. Verify power, network and the MQTT connection." : "Operating within limits. Continue routine monitoring."}</p>
              <button className="ghost-btn" onClick={() => setForm({ machine_id: m.id, title: top ? top.text.slice(0, 90) : `Routine inspection - ${m.name}`, priority: top?.priority === "urgent" ? "urgent" : top?.priority || "medium", note: "" })}>
                <ClipboardCheck size={14} /> {top ? "Create work order" : "Schedule inspection"}
              </button>
            </div>
          );
        })}
      </div>

      <section className="alerts-table-panel">
        <div className="panel-heading"><div><span className="small-label">NEW</span><h3>Create work order</h3></div></div>
        <form className="order-form" onSubmit={submit}>
          <select value={form.machine_id} onChange={(e) => setForm({ ...form, machine_id: e.target.value })}>
            {ctx.machines.map((m) => <option key={m.id} value={m.id}>{m.code} · {m.name}</option>)}
          </select>
          <input value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} placeholder="What needs to be done?" minLength={3} maxLength={160} required />
          <select value={form.priority} onChange={(e) => setForm({ ...form, priority: e.target.value })}>
            {["low", "medium", "high", "urgent"].map((p) => <option key={p} value={p}>{p}</option>)}
          </select>
          <input value={form.note} onChange={(e) => setForm({ ...form, note: e.target.value })} placeholder="Notes (optional)" maxLength={2000} />
          <button className="ack-btn" disabled={busy}><ClipboardCheck size={15} /> Create</button>
        </form>
      </section>

      <section className="alerts-table-panel">
        <div className="panel-heading"><div><span className="small-label">WORK ORDERS</span><h3>Maintenance queue</h3></div><span className="alert-counter">{orders.filter((o) => o.status !== "done").length}</span></div>
        {orders.length === 0 ? <Empty icon={CheckCircle2} title="No work orders" text="Create one from a recommendation above." /> : orders.map((o) => (
          <div className={`event-row order ${o.status} prio-${o.priority}`} key={o.id}>
            <div className="event-severity"><Wrench size={17} /></div>
            <div><strong>#{o.id} · {code(o.machine_id)} · {o.title}</strong><span>{o.priority.toUpperCase()} · {o.status.replace("_", " ")} · by {o.created_by} · {fmtDateTime(o.created_at)}{o.note ? ` · ${o.note}` : ""}</span></div>
            <b>{o.status.replace("_", " ").toUpperCase()}</b>
            <button className="ghost-btn tiny" onClick={() => advance(o)}>{NEXT_LABEL[o.status] || "Update"}</button>
          </div>
        ))}
      </section>
    </>
  );
}
