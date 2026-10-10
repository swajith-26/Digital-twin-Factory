import { Factory, RotateCcw } from "lucide-react";
import { PageHero } from "../components/common";
import MachineDetail from "../components/MachineDetail";
import { Scene3D } from "./Overview";
import { uiStatus } from "../lib/format";

export default function FactoryPage({ ctx }) {
  const zones = [...new Set(ctx.machines.map((m) => m.zone).filter(Boolean))];
  return (
    <>
      <PageHero icon={Factory} eyebrow="DIGITAL TWIN VISUALIZATION" title="3D Factory Command View"
        text="A virtual replica of the production floor driven by live data. Select an asset, inspect its state, rotate the model." />
      <div className="factory-toolbar">
        <div>
          <span className="status-badge healthy"><i />LIVE DIGITAL TWIN</span>
          <span className="toolbar-note">{ctx.machines.length} assets · {zones.length} zones · state updates the moment data arrives</span>
        </div>
        <button className="ghost-btn" onClick={() => ctx.setSelectedId(ctx.machines[0]?.id)}><RotateCcw size={14} /> Reset focus</button>
      </div>
      <section className="full-factory-layout">
        <div className="factory-panel"><Scene3D ctx={ctx} detailed /></div>
        <MachineDetail machine={ctx.selected} ctx={ctx} />
      </section>
      <div className="zone-strip">
        {zones.map((zone) => (
          <div key={zone}>
            <span>{zone.split("·")[0].trim().toUpperCase()}</span>
            <strong>{zone.split("·")[1]?.trim() || zone}</strong>
            <small>{ctx.machines.filter((m) => m.zone === zone).map((m) => `${m.code} ${uiStatus(m.status) === "healthy" ? "●" : "▲"}`).join(" · ")}</small>
          </div>
        ))}
      </div>
    </>
  );
}
