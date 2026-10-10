import { Component } from "react";
import { STATUS_LABEL, uiStatus } from "../lib/format";

export function PageHero({ icon: Icon, eyebrow, title, text }) {
  return (
    <section className="page-hero">
      <div className="page-hero-icon"><Icon size={25} /></div>
      <div>
        <div className="hero-kicker">{eyebrow}</div>
        <h2>{title}</h2>
        <p>{text}</p>
      </div>
    </section>
  );
}

export function Kpi({ label, value, icon: Icon, tone = "" }) {
  return (
    <div className={`kpi-card ${tone}`}>
      <div className="kpi-icon"><Icon size={19} /></div>
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

export function SectionTitle({ number, title, sub, children }) {
  return (
    <section className="section-title">
      <div>
        <span className="section-number">{number}</span>
        <div><h2>{title}</h2><p>{sub}</p></div>
      </div>
      {children}
    </section>
  );
}

export function StatusBadge({ status }) {
  const ui = uiStatus(status);
  return <span className={`status-badge ${ui}`}><i />{STATUS_LABEL[ui]}</span>;
}

export function Empty({ icon: Icon, title, text }) {
  return (
    <div className="all-clear large">
      <Icon size={40} />
      <strong>{title}</strong>
      <span>{text}</span>
    </div>
  );
}

/** A failing widget (e.g. no WebGL for the 3D view) must never blank the whole dashboard. */
export class ErrorBoundary extends Component {
  state = { failed: false };

  static getDerivedStateFromError() {
    return { failed: true };
  }

  componentDidCatch(error) {
    console.error(`${this.props.label || "Component"} failed:`, error);
  }

  render() {
    if (this.state.failed) {
      return (
        <div className="widget-error">
          <strong>{this.props.label || "This view"} is unavailable</strong>
          <span>{this.props.hint || "Reload the page. If it persists, check the browser console."}</span>
        </div>
      );
    }
    return this.props.children;
  }
}
