import { useState, useEffect, useRef, useCallback } from "react";

// ─── Constants ────────────────────────────────────────────────────────────────
const WS_URL  = "ws://localhost:8000/api/ws";
const API_URL = "http://localhost:8000/api";

const AGENTS = [
  { id:"scanner",   name:"SCANNER",       role:"Universe Scan",     icon:"⊙", color:"#38bdf8", col:0 },
  { id:"tech",      name:"TECHNICALS",    role:"TA / Indicators",   icon:"⌇", color:"#818cf8", col:1 },
  { id:"sentiment", name:"SENTIMENT",     role:"News & Social",     icon:"◎", color:"#fbbf24", col:1 },
  { id:"options",   name:"OPTIONS FLOW",  role:"Unusual Activity",  icon:"◈", color:"#c084fc", col:1 },
  { id:"macro",     name:"MACRO",         role:"Economic Data",     icon:"◉", color:"#34d399", col:1 },
  { id:"risk",      name:"RISK MGR",      role:"Risk Control",      icon:"⊛", color:"#fb923c", col:2 },
  { id:"pm",        name:"PORT. MANAGER", role:"Final Authority",   icon:"✦", color:"#fde047", col:2, isLeader:true },
  { id:"executor",  name:"EXECUTOR",      role:"Order Routing",     icon:"⊡", color:"#2dd4bf", col:3 },
];

const LEVEL_COLOR = { INFO:"#94a3b8", WARN:"#fbbf24", ERROR:"#f43f5e", DEBUG:"#475569" };

// ─── Helpers ──────────────────────────────────────────────────────────────────
const fmt$ = (n, decimals=0) => {
  if (n == null) return "—";
  const abs = Math.abs(n).toFixed(decimals);
  const commas = abs.replace(/\B(?=(\d{3})+(?!\d))/g, ",");
  return (n >= 0 ? "+" : "-") + "$" + commas;
};
const fmtPct = n => n == null ? "—" : (n >= 0 ? "+" : "") + n.toFixed(2) + "%";
const fmtTime = ts => {
  if (!ts) return "";
  const d = new Date(ts);
  return d.toLocaleTimeString("en-US", { hour12: false, hour:"2-digit", minute:"2-digit", second:"2-digit" });
};
const fmtEquity = n => "$" + (n||0).toFixed(0).replace(/\B(?=(\d{3})+(?!\d))/g,",");

// ─── CSS ──────────────────────────────────────────────────────────────────────
const CSS = `
@import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@300;400;500;600;700&family=Chakra+Petch:wght@300;400;500;600;700&display=swap');

*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

:root {
  --bg0: #020408;
  --bg1: #060d14;
  --bg2: #0a1520;
  --bg3: #0f1e2e;
  --border: #132035;
  --border2: #1c3050;
  --text: #8fb5d4;
  --text2: #5a7fa0;
  --muted: #2a4060;
  --mono: 'IBM Plex Mono', monospace;
  --sans: 'Chakra Petch', sans-serif;
  --sky: #38bdf8;
  --violet: #818cf8;
  --amber: #fbbf24;
  --emerald: #34d399;
  --rose: #f43f5e;
  --orange: #fb923c;
  --gold: #fde047;
  --teal: #2dd4bf;
  --purple: #c084fc;
}

html, body, #root { height: 100%; }

body {
  background: var(--bg0);
  color: var(--text);
  font-family: var(--mono);
  font-size: 11px;
  overflow: hidden;
}

::-webkit-scrollbar { width: 3px; height: 3px; }
::-webkit-scrollbar-track { background: transparent; }
::-webkit-scrollbar-thumb { background: var(--border2); border-radius: 2px; }

/* ── Layout ── */
.app {
  display: grid;
  grid-template-rows: 44px 1fr;
  grid-template-columns: 240px 1fr 300px;
  grid-template-areas:
    "header header header"
    "agents main feed";
  height: 100vh;
  gap: 0;
}

/* ── Header ── */
.header {
  grid-area: header;
  display: flex;
  align-items: center;
  gap: 24px;
  padding: 0 16px;
  background: var(--bg1);
  border-bottom: 1px solid var(--border);
  position: relative;
  overflow: hidden;
}

.header::after {
  content: '';
  position: absolute;
  bottom: 0; left: 0; right: 0;
  height: 1px;
  background: linear-gradient(90deg, transparent, var(--sky), transparent);
  opacity: 0.4;
}

.logo {
  font-family: var(--sans);
  font-size: 14px;
  font-weight: 700;
  letter-spacing: 3px;
  color: #fff;
  text-transform: uppercase;
}

.logo span { color: var(--sky); }

.header-stats {
  display: flex;
  gap: 20px;
  margin-left: auto;
}

.hstat {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  gap: 1px;
}

.hstat-label {
  font-size: 8px;
  color: var(--text2);
  letter-spacing: 1px;
  text-transform: uppercase;
}

.hstat-value {
  font-size: 13px;
  font-weight: 600;
  font-family: var(--sans);
  letter-spacing: 1px;
}

.pos { color: var(--emerald); }
.neg { color: var(--rose); }
.neu { color: var(--text); }

.cycle-badge {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 4px 10px;
  border: 1px solid var(--border2);
  border-radius: 2px;
  font-size: 9px;
  letter-spacing: 1px;
  text-transform: uppercase;
}

.dot-pulse {
  width: 5px; height: 5px;
  border-radius: 50%;
  background: var(--emerald);
  box-shadow: 0 0 6px var(--emerald);
  animation: pulse 1.5s ease-in-out infinite;
}

.dot-pulse.paused { background: var(--amber); box-shadow: 0 0 6px var(--amber); animation: none; }
.dot-pulse.error  { background: var(--rose);  box-shadow: 0 0 6px var(--rose);  animation: none; }

.btn {
  padding: 5px 12px;
  border: 1px solid var(--border2);
  background: transparent;
  color: var(--text);
  font-family: var(--mono);
  font-size: 9px;
  letter-spacing: 1px;
  text-transform: uppercase;
  cursor: pointer;
  transition: all 0.15s;
  border-radius: 2px;
}
.btn:hover { background: var(--bg3); border-color: var(--sky); color: var(--sky); }
.btn.primary { border-color: var(--sky); color: var(--sky); }
.btn.primary:hover { background: rgba(56,189,248,0.1); }

/* ── Agent Panel ── */
.agents-panel {
  grid-area: agents;
  background: var(--bg1);
  border-right: 1px solid var(--border);
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.panel-title {
  padding: 10px 14px 8px;
  font-size: 8px;
  letter-spacing: 2px;
  color: var(--muted);
  text-transform: uppercase;
  border-bottom: 1px solid var(--border);
}

.agent-list { flex: 1; overflow-y: auto; padding: 8px 0; }

.agent-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 14px;
  cursor: pointer;
  transition: background 0.1s;
  border-left: 2px solid transparent;
  position: relative;
}

.agent-item:hover { background: var(--bg2); }
.agent-item.active { background: var(--bg2); }
.agent-item.active::before {
  content: '';
  position: absolute;
  left: 0; top: 0; bottom: 0;
  width: 2px;
  background: var(--agent-color);
  box-shadow: 0 0 8px var(--agent-color);
}

.agent-icon {
  font-size: 14px;
  width: 22px;
  text-align: center;
  color: var(--agent-color);
  filter: drop-shadow(0 0 4px var(--agent-color));
}

.agent-info { flex: 1; min-width: 0; }
.agent-name { font-family: var(--sans); font-size: 10px; font-weight: 600; letter-spacing: 1px; color: #fff; }
.agent-role { font-size: 8px; color: var(--text2); margin-top: 1px; }

.agent-status {
  font-size: 7px;
  letter-spacing: 1px;
  padding: 2px 5px;
  border-radius: 1px;
  text-transform: uppercase;
}

.status-RUNNING { background: rgba(56,189,248,0.15); color: var(--sky); animation: blink 1s infinite; }
.status-IDLE    { background: transparent; color: var(--muted); }
.status-ERROR   { background: rgba(244,63,94,0.15); color: var(--rose); }

@keyframes blink { 0%,100%{opacity:1} 50%{opacity:0.4} }
@keyframes pulse { 0%,100%{opacity:1} 50%{opacity:0.3} }
@keyframes slideIn { from{opacity:0;transform:translateX(-6px)} to{opacity:1;transform:translateX(0)} }
@keyframes fadeIn  { from{opacity:0} to{opacity:1} }

/* ── Main Area ── */
.main-area {
  grid-area: main;
  display: grid;
  grid-template-rows: 100px 1fr 160px;
  overflow: hidden;
  background: var(--bg0);
}

/* ── Portfolio Row ── */
.portfolio-row {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 1px;
  background: var(--border);
  border-bottom: 1px solid var(--border);
}

.portfolio-card {
  background: var(--bg1);
  padding: 12px 18px;
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.pc-header {
  display: flex;
  align-items: center;
  gap: 8px;
}

.pc-mode {
  font-family: var(--sans);
  font-size: 9px;
  font-weight: 700;
  letter-spacing: 2px;
  padding: 2px 7px;
  border-radius: 1px;
}

.pc-mode.paper { background: rgba(129,140,248,0.15); color: var(--violet); border: 1px solid rgba(129,140,248,0.3); }
.pc-mode.live  { background: rgba(244,63,94,0.12);   color: var(--rose);   border: 1px solid rgba(244,63,94,0.3); }

.pc-equity {
  font-family: var(--sans);
  font-size: 22px;
  font-weight: 700;
  color: #fff;
  letter-spacing: -0.5px;
}

.pc-stats { display: flex; gap: 16px; }

.pc-stat { display: flex; flex-direction: column; gap: 1px; }
.pc-stat-label { font-size: 7px; color: var(--text2); letter-spacing: 1px; text-transform: uppercase; }
.pc-stat-value { font-size: 11px; font-weight: 600; }

/* ── Log View ── */
.log-view {
  overflow-y: auto;
  padding: 6px 0;
  background: var(--bg0);
}

.log-entry {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  padding: 5px 16px;
  border-bottom: 1px solid rgba(19,32,53,0.5);
  animation: slideIn 0.2s ease;
  transition: background 0.1s;
}

.log-entry:hover { background: var(--bg1); }
.log-entry.flash { animation: flash 0.6s ease; }

@keyframes flash { 0%{background:rgba(56,189,248,0.08)} 100%{background:transparent} }

.log-ts { color: var(--muted); font-size: 9px; white-space: nowrap; padding-top: 1px; min-width: 70px; }

.log-agent {
  font-family: var(--sans);
  font-size: 8px;
  font-weight: 600;
  letter-spacing: 1px;
  padding: 1px 5px;
  border-radius: 1px;
  white-space: nowrap;
  min-width: 90px;
  text-align: center;
}

.log-msg { color: var(--text); font-size: 10px; line-height: 1.5; flex: 1; }

.log-entry.level-WARN  .log-msg { color: var(--amber); }
.log-entry.level-ERROR .log-msg { color: var(--rose); }

/* ── Orders Table ── */
.orders-panel {
  background: var(--bg1);
  border-top: 1px solid var(--border);
  overflow: hidden;
  display: flex;
  flex-direction: column;
}

.orders-header {
  padding: 7px 16px;
  font-size: 8px;
  letter-spacing: 2px;
  color: var(--muted);
  text-transform: uppercase;
  border-bottom: 1px solid var(--border);
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.orders-list { overflow-y: auto; flex: 1; }

.order-row {
  display: grid;
  grid-template-columns: 60px 40px 50px 70px 50px 70px 1fr;
  gap: 0;
  padding: 5px 16px;
  border-bottom: 1px solid rgba(19,32,53,0.5);
  align-items: center;
  animation: fadeIn 0.3s ease;
}

.order-row:hover { background: var(--bg2); }

.order-cell { font-size: 9px; }

.order-symbol { font-family: var(--sans); font-weight: 600; font-size: 11px; color: #fff; }
.order-side-buy  { color: var(--emerald); font-weight: 700; font-size: 9px; letter-spacing: 1px; }
.order-side-sell { color: var(--rose);    font-weight: 700; font-size: 9px; letter-spacing: 1px; }

.order-status {
  font-size: 7px;
  letter-spacing: 1px;
  padding: 1px 4px;
  border-radius: 1px;
  text-transform: uppercase;
  white-space: nowrap;
}

.status-filled   { background: rgba(52,211,153,0.15); color: var(--emerald); }
.status-pending  { background: rgba(251,191,36,0.12); color: var(--amber); }
.status-rejected { background: rgba(244,63,94,0.12);  color: var(--rose); }

/* ── Feed Panel ── */
.feed-panel {
  grid-area: feed;
  background: var(--bg1);
  border-left: 1px solid var(--border);
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.feed-tabs {
  display: flex;
  border-bottom: 1px solid var(--border);
}

.feed-tab {
  flex: 1;
  padding: 9px 8px;
  font-size: 8px;
  letter-spacing: 1.5px;
  text-transform: uppercase;
  color: var(--text2);
  cursor: pointer;
  border-bottom: 2px solid transparent;
  text-align: center;
  transition: all 0.15s;
}

.feed-tab:hover { color: var(--text); background: var(--bg2); }
.feed-tab.active { color: var(--sky); border-bottom-color: var(--sky); background: var(--bg2); }

.feed-content { flex: 1; overflow-y: auto; padding: 8px; }

/* ── Signal Cards ── */
.signal-card {
  background: var(--bg2);
  border: 1px solid var(--border2);
  border-radius: 2px;
  padding: 10px 12px;
  margin-bottom: 6px;
  animation: slideIn 0.25s ease;
  position: relative;
  overflow: hidden;
}

.signal-card::before {
  content: '';
  position: absolute;
  left: 0; top: 0; bottom: 0;
  width: 2px;
}

.signal-card.buy::before  { background: var(--emerald); box-shadow: 0 0 8px var(--emerald); }
.signal-card.sell::before { background: var(--rose);    box-shadow: 0 0 8px var(--rose); }
.signal-card.hold::before { background: var(--amber);   box-shadow: 0 0 8px var(--amber); }

.sc-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px; }
.sc-symbol { font-family: var(--sans); font-size: 14px; font-weight: 700; color: #fff; }
.sc-dir { font-family: var(--sans); font-size: 10px; font-weight: 700; letter-spacing: 2px; }
.sc-dir.buy  { color: var(--emerald); }
.sc-dir.sell { color: var(--rose); }
.sc-dir.hold { color: var(--amber); }

.sc-meta { display: flex; gap: 8px; margin-bottom: 5px; flex-wrap: wrap; }
.sc-tag {
  font-size: 7px;
  letter-spacing: 1px;
  padding: 1px 5px;
  border-radius: 1px;
  background: var(--bg3);
  color: var(--text2);
  border: 1px solid var(--border);
  text-transform: uppercase;
}

.sc-reasoning { font-size: 9px; color: var(--text2); line-height: 1.5; }

.conviction-bar {
  height: 2px;
  background: var(--border);
  border-radius: 1px;
  margin-top: 8px;
  overflow: hidden;
}

.conviction-fill {
  height: 100%;
  border-radius: 1px;
  transition: width 0.3s ease;
}

/* ── Cycle progress ── */
.cycle-progress {
  padding: 6px 16px;
  background: var(--bg1);
  border-top: 1px solid var(--border);
  display: flex;
  align-items: center;
  gap: 10px;
}

.progress-track {
  flex: 1;
  height: 2px;
  background: var(--border);
  border-radius: 1px;
  overflow: hidden;
}

.progress-fill {
  height: 100%;
  background: linear-gradient(90deg, var(--sky), var(--violet));
  transition: width 1s linear;
  border-radius: 1px;
}

.progress-label { font-size: 8px; color: var(--text2); letter-spacing: 1px; white-space: nowrap; }

/* ── Regime badge ── */
.regime-badge {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 3px 8px;
  border-radius: 2px;
  font-family: var(--sans);
  font-size: 9px;
  font-weight: 600;
  letter-spacing: 1.5px;
  text-transform: uppercase;
}

.regime-RISK_ON         { background: rgba(52,211,153,0.12); color: var(--emerald); border: 1px solid rgba(52,211,153,0.25); }
.regime-RISK_OFF        { background: rgba(244,63,94,0.12);  color: var(--rose);    border: 1px solid rgba(244,63,94,0.25); }
.regime-NEUTRAL         { background: rgba(148,163,184,0.1); color: var(--text);    border: 1px solid var(--border2); }
.regime-HIGH_VOLATILITY { background: rgba(251,191,36,0.12); color: var(--amber);   border: 1px solid rgba(251,191,36,0.25); }
.regime-RATE_SENSITIVE  { background: rgba(192,132,252,0.12);color: var(--purple);  border: 1px solid rgba(192,132,252,0.25); }

/* ── Connection overlay ── */
.conn-bar {
  position: fixed;
  bottom: 0; left: 0; right: 0;
  padding: 4px 16px;
  font-size: 8px;
  letter-spacing: 1px;
  text-align: center;
  z-index: 100;
}

.conn-bar.connecting { background: rgba(251,191,36,0.15); color: var(--amber); }
.conn-bar.error      { background: rgba(244,63,94,0.15);  color: var(--rose); }

/* ── Scanlines overlay ── */
.scanline {
  position: fixed;
  inset: 0;
  pointer-events: none;
  z-index: 1000;
  background: repeating-linear-gradient(
    0deg,
    transparent,
    transparent 2px,
    rgba(0,0,0,0.03) 2px,
    rgba(0,0,0,0.03) 4px
  );
}

/* ── Tabs on main ── */
.main-tabs {
  display: flex;
  gap: 0;
  border-bottom: 1px solid var(--border);
  background: var(--bg1);
  padding: 0 16px;
}

.main-tab {
  padding: 8px 14px;
  font-size: 8px;
  letter-spacing: 2px;
  text-transform: uppercase;
  color: var(--text2);
  cursor: pointer;
  border-bottom: 2px solid transparent;
  transition: all 0.15s;
}

.main-tab:hover { color: var(--text); }
.main-tab.active { color: var(--sky); border-bottom-color: var(--sky); }
`;

// ─── Sub-components ───────────────────────────────────────────────────────────

function PortfolioCard({ data, mode }) {
  const equity   = data?.equity   ?? (mode === "PAPER" ? 100000 : 10000);
  const dayPnl   = data?.day_pnl  ?? 0;
  const totalPnl = data?.total_pnl ?? 0;
  const cash     = data?.cash      ?? equity;
  const positions = data?.positions_json ?? [];

  return (
    <div className="portfolio-card">
      <div className="pc-header">
        <span className={`pc-mode ${mode.toLowerCase()}`}>{mode}</span>
        {mode === "LIVE" && <span style={{ fontSize:"8px", color:"var(--rose)", letterSpacing:"1px" }}>● REAL MONEY</span>}
      </div>
      <div className="pc-equity">{fmtEquity(equity)}</div>
      <div className="pc-stats">
        <div className="pc-stat">
          <span className="pc-stat-label">Day P&L</span>
          <span className={`pc-stat-value ${dayPnl >= 0 ? "pos" : "neg"}`}>{fmt$(dayPnl)}</span>
        </div>
        <div className="pc-stat">
          <span className="pc-stat-label">Total P&L</span>
          <span className={`pc-stat-value ${totalPnl >= 0 ? "pos" : "neg"}`}>{fmt$(totalPnl)}</span>
        </div>
        <div className="pc-stat">
          <span className="pc-stat-label">Cash</span>
          <span className="pc-stat-value neu">{fmtEquity(cash)}</span>
        </div>
        <div className="pc-stat">
          <span className="pc-stat-label">Positions</span>
          <span className="pc-stat-value neu">{positions.length}</span>
        </div>
      </div>
    </div>
  );
}

function AgentRow({ agent, status, isActive, onClick }) {
  return (
    <div
      className={`agent-item ${isActive ? "active" : ""}`}
      style={{ "--agent-color": agent.color }}
      onClick={onClick}
    >
      <span className="agent-icon">{agent.icon}</span>
      <div className="agent-info">
        <div className="agent-name">{agent.name}</div>
        <div className="agent-role">{agent.role}</div>
      </div>
      <span className={`agent-status status-${status || "IDLE"}`}>
        {status || "idle"}
      </span>
    </div>
  );
}

function LogEntry({ log }) {
  const agent = AGENTS.find(a => a.id === log.agent_id);
  const color = agent?.color ?? "#94a3b8";

  return (
    <div className={`log-entry level-${log.level}`}>
      <span className="log-ts">{fmtTime(log.ts || log.created_at)}</span>
      <span
        className="log-agent"
        style={{
          backgroundColor: color + "18",
          color,
          border: `1px solid ${color}30`,
        }}
      >
        {log.agent_name || log.agent_id}
      </span>
      <span className="log-msg">{log.message}</span>
    </div>
  );
}

function SignalCard({ signal }) {
  const dir   = (signal.direction || signal.action || "HOLD").toLowerCase();
  const conv  = signal.conviction ?? 0;
  const color = dir === "buy" ? "var(--emerald)" : dir === "sell" ? "var(--rose)" : "var(--amber)";

  return (
    <div className={`signal-card ${dir}`}>
      <div className="sc-header">
        <span className="sc-symbol">{signal.symbol}</span>
        <span className={`sc-dir ${dir}`}>{dir.toUpperCase()}</span>
      </div>
      <div className="sc-meta">
        <span className="sc-tag">{signal.source_agent || "PM"}</span>
        <span className="sc-tag">conv {(conv * 100).toFixed(0)}%</span>
        {signal.flow_type && <span className="sc-tag">{signal.flow_type}</span>}
        {signal.catalyst  && <span className="sc-tag">catalyst</span>}
      </div>
      <div className="sc-reasoning">{signal.reasoning || "No reasoning provided"}</div>
      <div className="conviction-bar">
        <div
          className="conviction-fill"
          style={{ width: `${conv * 100}%`, background: color }}
        />
      </div>
    </div>
  );
}

function OrderRow({ order }) {
  const pStatus = (order.paper_status || "PENDING").toLowerCase();
  const lStatus = (order.live_status  || "PENDING").toLowerCase();

  return (
    <div className="order-row">
      <span className="order-cell order-symbol">{order.symbol}</span>
      <span className={`order-cell order-side-${order.side?.toLowerCase()}`}>
        {order.side}
      </span>
      <span className="order-cell neu">{order.qty}sh</span>
      <span className="order-cell neu">${order.limit_price?.toFixed(2) ?? "—"}</span>
      <span className="order-cell" style={{ color:"var(--text2)" }}>
        {(order.pm_conviction * 100).toFixed(0)}%
      </span>
      <span className={`order-cell order-status status-${pStatus}`}>P:{pStatus}</span>
      <span className={`order-cell order-status status-${lStatus}`}>L:{lStatus}</span>
    </div>
  );
}

// ─── Main App ─────────────────────────────────────────────────────────────────
export default function App() {
  const [logs,         setLogs]         = useState([]);
  const [signals,      setSignals]      = useState([]);
  const [orders,       setOrders]       = useState([]);
  const [agentStatus,  setAgentStatus]  = useState({});
  const [paperPort,    setPaperPort]    = useState(null);
  const [livePort,     setLivePort]     = useState(null);
  const [currentCycle, setCurrentCycle] = useState(null);
  const [regime,       setRegime]       = useState(null);
  const [wsState,      setWsState]      = useState("connecting"); // connecting|open|closed|error
  const [activeAgent,  setActiveAgent]  = useState(null);
  const [activeTab,    setActiveTab]    = useState("logs");
  const [feedTab,      setFeedTab]      = useState("signals");
  const [cycleTimer,   setCycleTimer]   = useState(0);
  const [cyclePct,     setCyclePct]     = useState(0);

  const wsRef      = useRef(null);
  const logEndRef  = useRef(null);
  const timerRef   = useRef(null);
  const CYCLE_SECS = 300;

  // ── Fetch initial dashboard data ───────────────────────────────────────────
  useEffect(() => {
    fetch(`${API_URL}/dashboard`)
      .then(r => r.json())
      .then(d => {
        if (d.recent_logs)   setLogs(d.recent_logs.slice(-200).reverse());
        if (d.recent_orders) setOrders(d.recent_orders);
        if (d.paper_portfolio) setPaperPort(d.paper_portfolio);
        if (d.live_portfolio)  setLivePort(d.live_portfolio);
        if (d.current_cycle)   setCurrentCycle(d.current_cycle);
        if (d.agent_statuses)  setAgentStatus(d.agent_statuses);
      })
      .catch(() => {});
  }, []);

  // ── WebSocket ──────────────────────────────────────────────────────────────
  const connectWS = useCallback(() => {
    const ws = new WebSocket(WS_URL);
    wsRef.current = ws;
    setWsState("connecting");

    ws.onopen  = () => setWsState("open");
    ws.onclose = () => { setWsState("closed"); setTimeout(connectWS, 3000); };
    ws.onerror = () => setWsState("error");

    ws.onmessage = (e) => {
      try {
        const { event, payload } = JSON.parse(e.data);

        if (event === "agent_log") {
          setLogs(prev => [...prev.slice(-399), payload]);
        }
        if (event === "agent_status") {
          setAgentStatus(prev => ({ ...prev, [payload.agent_id]: payload.status }));
        }
        if (event === "order") {
          setOrders(prev => [payload, ...prev.slice(0, 49)]);
        }
        if (event === "portfolio") {
          if (payload.mode === "PAPER") setPaperPort(payload);
          else setLivePort(payload);
        }
        if (event === "cycle") {
          setCurrentCycle(payload);
          setCycleTimer(CYCLE_SECS);
          setCyclePct(0);
        }
        if (event === "signal") {
          setSignals(prev => [payload, ...prev.slice(0, 49)]);
        }
        if (event === "macro_regime") {
          setRegime(payload);
        }
      } catch {}
    };
  }, []);

  useEffect(() => { connectWS(); return () => wsRef.current?.close(); }, [connectWS]);

  // ── Cycle countdown ────────────────────────────────────────────────────────
  useEffect(() => {
    timerRef.current = setInterval(() => {
      setCycleTimer(t => {
        const next = t > 0 ? t - 1 : CYCLE_SECS;
        setCyclePct(((CYCLE_SECS - next) / CYCLE_SECS) * 100);
        return next;
      });
    }, 1000);
    return () => clearInterval(timerRef.current);
  }, []);

  // ── Auto-scroll logs ───────────────────────────────────────────────────────
  useEffect(() => {
    if (activeTab === "logs") {
      logEndRef.current?.scrollIntoView({ behavior: "smooth" });
    }
  }, [logs, activeTab]);

  // ── Filtered logs ──────────────────────────────────────────────────────────
  const visibleLogs = activeAgent
    ? logs.filter(l => l.agent_id === activeAgent)
    : logs;

  const triggerCycle = async () => {
    try {
      await fetch(`${API_URL}/cycle/trigger`, { method: "POST" });
    } catch {}
  };

  const mins = String(Math.floor(cycleTimer / 60)).padStart(2, "0");
  const secs = String(cycleTimer % 60).padStart(2, "0");

  return (
    <>
      <style>{CSS}</style>
      <div className="scanline" />

      <div className="app">
        {/* ── Header ── */}
        <header className="header">
          <div className="logo">AI<span>TRADE</span> AGENTS</div>

          {regime && (
            <div className={`regime-badge regime-${regime.regime}`}>
              {regime.regime?.replace("_", " ")}
            </div>
          )}

          <div className="cycle-badge">
            <span className={`dot-pulse ${wsState !== "open" ? "paused" : ""}`} />
            CYCLE #{currentCycle?.id ?? "—"} &nbsp;·&nbsp;
            NEXT {mins}:{secs}
          </div>

          <div className="header-stats">
            <div className="hstat">
              <span className="hstat-label">Paper P&L</span>
              <span className={`hstat-value ${(paperPort?.day_pnl ?? 0) >= 0 ? "pos" : "neg"}`}>
                {fmt$(paperPort?.day_pnl ?? 0)}
              </span>
            </div>
            <div className="hstat">
              <span className="hstat-label">Live P&L</span>
              <span className={`hstat-value ${(livePort?.day_pnl ?? 0) >= 0 ? "pos" : "neg"}`}>
                {fmt$(livePort?.day_pnl ?? 0)}
              </span>
            </div>
            <div className="hstat">
              <span className="hstat-label">Orders</span>
              <span className="hstat-value neu">{orders.length}</span>
            </div>
            <div className="hstat">
              <span className="hstat-label">Signals</span>
              <span className="hstat-value neu">{signals.length}</span>
            </div>
          </div>

          <button className="btn primary" onClick={triggerCycle}>▶ TRIGGER CYCLE</button>
        </header>

        {/* ── Agent Sidebar ── */}
        <aside className="agents-panel">
          <div className="panel-title">Agent Hierarchy</div>
          <div className="agent-list">
            {AGENTS.map(ag => (
              <AgentRow
                key={ag.id}
                agent={ag}
                status={agentStatus[ag.id]}
                isActive={activeAgent === ag.id}
                onClick={() => setActiveAgent(activeAgent === ag.id ? null : ag.id)}
              />
            ))}
          </div>

          <div style={{ padding:"10px 14px", borderTop:"1px solid var(--border)" }}>
            <div style={{ fontSize:"8px", color:"var(--muted)", letterSpacing:"1.5px", marginBottom:"6px" }}>
              BROKER
            </div>
            <div style={{ fontSize:"9px", color:"var(--text2)", lineHeight:"1.8" }}>
              <div>● PAPER &nbsp;<span style={{ color:"var(--violet)" }}>Alpaca Markets</span></div>
              <div>● LIVE &nbsp;&nbsp;<span style={{ color:"var(--rose)" }}>Alpaca Markets</span></div>
            </div>
          </div>

          {activeAgent && (
            <div style={{ padding:"8px 14px", borderTop:"1px solid var(--border)" }}>
              <button
                className="btn"
                style={{ width:"100%", fontSize:"8px" }}
                onClick={() => setActiveAgent(null)}
              >
                ✕ CLEAR FILTER
              </button>
            </div>
          )}
        </aside>

        {/* ── Main Area ── */}
        <main className="main-area">
          {/* Portfolio cards */}
          <div className="portfolio-row">
            <PortfolioCard data={paperPort} mode="PAPER" />
            <PortfolioCard data={livePort}  mode="LIVE" />
          </div>

          {/* Log / Orders tabs */}
          <div style={{ display:"flex", flexDirection:"column", overflow:"hidden" }}>
            <div className="main-tabs">
              {["logs","orders"].map(t => (
                <div
                  key={t}
                  className={`main-tab ${activeTab === t ? "active" : ""}`}
                  onClick={() => setActiveTab(t)}
                >
                  {t === "logs" ? `AGENT LOGS (${visibleLogs.length})` : `ORDERS (${orders.length})`}
                </div>
              ))}
              {activeAgent && (
                <div style={{ marginLeft:"auto", display:"flex", alignItems:"center", gap:"6px", fontSize:"8px", color:"var(--text2)" }}>
                  FILTER:
                  <span style={{ color: AGENTS.find(a => a.id === activeAgent)?.color }}>
                    {AGENTS.find(a => a.id === activeAgent)?.name}
                  </span>
                </div>
              )}
            </div>

            {activeTab === "logs" && (
              <div className="log-view" style={{ flex:1 }}>
                {visibleLogs.length === 0 && (
                  <div style={{ padding:"20px 16px", color:"var(--muted)", fontSize:"10px" }}>
                    Waiting for agent activity...
                  </div>
                )}
                {visibleLogs.map((log, i) => (
                  <LogEntry key={log.id ?? i} log={log} />
                ))}
                <div ref={logEndRef} />
              </div>
            )}

            {activeTab === "orders" && (
              <div style={{ flex:1, overflow:"hidden", display:"flex", flexDirection:"column" }}>
                <div style={{
                  display:"grid",
                  gridTemplateColumns:"60px 40px 50px 70px 50px 70px 1fr",
                  padding:"5px 16px",
                  fontSize:"7px",
                  color:"var(--muted)",
                  letterSpacing:"1.5px",
                  textTransform:"uppercase",
                  borderBottom:"1px solid var(--border)",
                  background:"var(--bg1)",
                }}>
                  <span>Symbol</span><span>Side</span><span>Qty</span>
                  <span>Price</span><span>Conv.</span><span>Paper</span><span>Live</span>
                </div>
                <div style={{ flex:1, overflowY:"auto" }}>
                  {orders.length === 0 && (
                    <div style={{ padding:"20px 16px", color:"var(--muted)", fontSize:"10px" }}>
                      No orders yet this session...
                    </div>
                  )}
                  {orders.map((o, i) => <OrderRow key={o.id ?? i} order={o} />)}
                </div>
              </div>
            )}
          </div>

          {/* Cycle progress bar */}
          <div className="cycle-progress">
            <span className="progress-label">CYCLE PROGRESS</span>
            <div className="progress-track">
              <div className="progress-fill" style={{ width: `${cyclePct}%` }} />
            </div>
            <span className="progress-label">{mins}:{secs}</span>
            <span className="progress-label" style={{ color:"var(--muted)" }}>
              · SIG {currentCycle?.signals_generated ?? 0}
              &nbsp;ORD {currentCycle?.orders_placed ?? 0}
            </span>
          </div>
        </main>

        {/* ── Right Feed ── */}
        <aside className="feed-panel">
          <div className="feed-tabs">
            {["signals", "macro"].map(t => (
              <div
                key={t}
                className={`feed-tab ${feedTab === t ? "active" : ""}`}
                onClick={() => setFeedTab(t)}
              >
                {t.toUpperCase()}
              </div>
            ))}
          </div>

          <div className="feed-content">
            {feedTab === "signals" && (
              <>
                {signals.length === 0 && (
                  <div style={{ color:"var(--muted)", fontSize:"10px", padding:"10px 4px" }}>
                    Awaiting signals...
                  </div>
                )}
                {signals.map((s, i) => <SignalCard key={s.id ?? i} signal={s} />)}
              </>
            )}

            {feedTab === "macro" && (
              <>
                {regime ? (
                  <div style={{ display:"flex", flexDirection:"column", gap:"8px" }}>
                    <div className={`regime-badge regime-${regime.regime}`} style={{ width:"fit-content" }}>
                      {regime.regime?.replace("_", " ")}
                    </div>

                    {[
                      { label:"VIX Level",    value: regime.vix_level ?? "—" },
                      { label:"VIX Trend",    value: regime.vix_trend ?? "—" },
                      { label:"Pos. Mult.",   value: regime.position_size_multiplier ? `${regime.position_size_multiplier}x` : "—" },
                      { label:"Event Risk",   value: regime.event_risk ?? "—" },
                      { label:"Key Event",    value: regime.key_event_today ?? "None" },
                    ].map(row => (
                      <div key={row.label} style={{
                        display:"flex", justifyContent:"space-between",
                        padding:"6px 0", borderBottom:"1px solid var(--border)",
                        fontSize:"9px",
                      }}>
                        <span style={{ color:"var(--text2)" }}>{row.label}</span>
                        <span style={{ color:"var(--text)" }}>{String(row.value)}</span>
                      </div>
                    ))}

                    {regime.favoured_sectors?.length > 0 && (
                      <div>
                        <div style={{ fontSize:"7px", color:"var(--muted)", letterSpacing:"1.5px", marginBottom:"5px", textTransform:"uppercase" }}>
                          Favoured Sectors
                        </div>
                        {regime.favoured_sectors.map(s => (
                          <div key={s} style={{ fontSize:"9px", color:"var(--emerald)", padding:"2px 0" }}>
                            ↑ {s}
                          </div>
                        ))}
                      </div>
                    )}

                    {regime.avoid_sectors?.length > 0 && (
                      <div>
                        <div style={{ fontSize:"7px", color:"var(--muted)", letterSpacing:"1.5px", marginBottom:"5px", textTransform:"uppercase" }}>
                          Avoid Sectors
                        </div>
                        {regime.avoid_sectors.map(s => (
                          <div key={s} style={{ fontSize:"9px", color:"var(--rose)", padding:"2px 0" }}>
                            ↓ {s}
                          </div>
                        ))}
                      </div>
                    )}

                    <div style={{ fontSize:"9px", color:"var(--text2)", lineHeight:"1.6", marginTop:"4px" }}>
                      {regime.reasoning}
                    </div>
                  </div>
                ) : (
                  <div style={{ color:"var(--muted)", fontSize:"10px", padding:"10px 4px" }}>
                    Awaiting macro assessment...
                  </div>
                )}
              </>
            )}
          </div>
        </aside>
      </div>

      {/* WebSocket status */}
      {wsState !== "open" && (
        <div className={`conn-bar ${wsState}`}>
          {wsState === "connecting" && "◌ CONNECTING TO TRADING SYSTEM..."}
          {wsState === "closed"     && "◌ RECONNECTING..."}
          {wsState === "error"      && "✕ CONNECTION ERROR — RETRYING"}
        </div>
      )}
    </>
  );
}
