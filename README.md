# 🤖 AI Trading Agents

A multi-agent AI intraday trading system with **paper + live simultaneous trading** via Alpaca Markets. 8 specialized Claude-powered agents collaborate under a hierarchical Portfolio Manager to scan, analyse, size, and execute trades every 5 minutes.

---

## 🏗 Architecture

```
┌─────────────────────────────────────────────────────────┐
│                      CYCLE (every 5 min)                │
│                                                         │
│  ┌──────────┐                                           │
│  │ SCANNER  │  Scans 40+ symbols → top 8-10 candidates │
│  └────┬─────┘                                           │
│       │ candidates + snapshots                          │
│       ▼  ┌───────────────────────────────────────────┐  │
│          │        PARALLEL ANALYSIS LAYER            │  │
│          │  ┌────────────┐  ┌────────────────────┐   │  │
│          │  │ TECHNICALS │  │    SENTIMENT       │   │  │
│          │  │ RSI/MACD/  │  │ News + Social +   │   │  │
│          │  │ BB/VWAP/   │  │ Analyst Ratings   │   │  │
│          │  │ EMA/ATR    │  └────────────────────┘   │  │
│          │  └────────────┘  ┌────────────────────┐   │  │
│          │  ┌────────────┐  │    OPTIONS FLOW    │   │  │
│          │  │   MACRO    │  │ Sweeps/Blocks/     │   │  │
│          │  │ VIX/Yield/ │  │ Dark Pool/Gamma    │   │  │
│          │  │ Regime     │  └────────────────────┘   │  │
│          │  └────────────┘                           │  │
│          └──────────────────┬────────────────────────┘  │
│                             │ all signals + regime       │
│                             ▼                           │
│                    ┌──────────────────┐                 │
│                    │   RISK MANAGER   │ ← gate         │
│                    │ Size/Stop/Sector │                 │
│                    └────────┬─────────┘                 │
│                             │ approve/reduce/reject      │
│                             ▼                           │
│                    ┌──────────────────┐                 │
│                    │ PORT. MANAGER ★  │ ← FINAL SAY    │
│                    │ Weighted signals │                 │
│                    │ Options 35%      │                 │
│                    │ Technicals 30%   │                 │
│                    │ Sentiment 20%    │                 │
│                    │ Macro 15%        │                 │
│                    └────────┬─────────┘                 │
│                             │ approved orders            │
│                             ▼                           │
│                    ┌──────────────────┐                 │
│                    │    EXECUTOR      │                 │
│                    │ PAPER ──► Alpaca │                 │
│                    │ LIVE  ──► Alpaca │                 │
│                    └──────────────────┘                 │
└─────────────────────────────────────────────────────────┘
```

---

## 📁 Project Structure

```
stockTrading/
├── main.py                      # FastAPI app + scheduler startup
├── orchestrator.py              # 5-min cycle pipeline manager
├── config.py                    # Pydantic settings (from .env)
├── requirements.txt
├── .env.example
│
├── agents/
│   ├── base_agent.py            # Abstract base: Claude AI + DB logging + WS broadcast
│   ├── scanner.py               # Universe scan → candidate list
│   ├── technicals.py            # RSI, MACD, BB, VWAP, EMA, ATR
│   ├── sentiment.py             # NewsAPI + RSS headlines → sentiment score
│   ├── options_flow.py          # Unusual activity: sweeps, blocks, dark pool
│   ├── macro.py                 # VIX, yields, economic indicators, regime
│   ├── risk_manager.py          # Position sizing, sector limits, daily loss halt
│   ├── portfolio_manager.py     # Weighted signal aggregation, final decision
│   └── executor.py              # Bracket orders → paper + live simultaneously
│
├── brokers/
│   ├── base_broker.py           # Abstract interface (add any broker here)
│   └── alpaca_broker.py         # Alpaca Markets implementation
│
├── models/
│   ├── database.py              # SQLAlchemy ORM models + async engine
│   └── schemas.py               # Pydantic v2 API schemas
│
├── api/
│   └── routes.py                # FastAPI routes + WebSocket manager
│
└── frontend/
    ├── package.json
    ├── vite.config.js
    ├── index.html
    └── src/
        ├── main.jsx
        └── App.jsx              # Full trading dashboard UI
```

---

## 🚀 Quick Start

### 1. Clone and configure

```bash
git clone https://github.com/yavuzalp/stockTrading.git
cd stockTrading
cp .env.example .env
# Edit .env with your API keys
```

### 2. Backend setup

```bash
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate

pip install -r requirements.txt

python main.py
# API running at http://localhost:8000
# WebSocket at  ws://localhost:8000/api/ws
```

### 3. Frontend setup

```bash
cd frontend
npm install
npm run dev
# Dashboard at http://localhost:3000
```

---

## 🔑 API Keys Required

| Key | Where to get | Used for |
|-----|-------------|---------|
| `ALPACA_PAPER_API_KEY` | [alpaca.markets](https://alpaca.markets) → Paper | Paper trading + market data |
| `ALPACA_LIVE_API_KEY`  | [alpaca.markets](https://alpaca.markets) → Live  | Live trading |
| `ANTHROPIC_API_KEY`    | [console.anthropic.com](https://console.anthropic.com) | All 8 AI agents |
| `NEWS_API_KEY`         | [newsapi.org](https://newsapi.org) (free tier ok) | Sentiment agent |
| `ALPHA_VANTAGE_KEY`    | [alphavantage.co](https://www.alphavantage.co) (free) | Macro agent |

---

## 📡 API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET`  | `/api/dashboard`         | Full dashboard summary |
| `GET`  | `/api/cycles`            | Recent trading cycles |
| `GET`  | `/api/cycles/{id}/logs`  | Agent logs for a cycle |
| `GET`  | `/api/cycles/{id}/signals` | Signals for a cycle |
| `GET`  | `/api/orders`            | Recent orders |
| `GET`  | `/api/portfolio`         | Current paper + live portfolio |
| `GET`  | `/api/portfolio/history` | Equity curve history |
| `POST` | `/api/cycle/trigger`     | Manually fire a cycle |
| `WS`   | `/api/ws`                | Live event stream |

### WebSocket Events

```jsonc
// agent_log — every agent action
{ "event": "agent_log", "payload": { "agent_id": "tech", "message": "...", "level": "INFO" } }

// agent_status — idle/running/error transitions
{ "event": "agent_status", "payload": { "agent_id": "pm", "status": "RUNNING" } }

// signal — new signal from any analyst agent
{ "event": "signal", "payload": { "symbol": "NVDA", "direction": "BUY", "conviction": 0.82 } }

// order — new approved order
{ "event": "order", "payload": { "symbol": "NVDA", "side": "BUY", "qty": 10 } }

// portfolio — portfolio snapshot update
{ "event": "portfolio", "payload": { "mode": "PAPER", "equity": 103420 } }

// macro_regime — macro assessment update
{ "event": "macro_regime", "payload": { "regime": "RISK_ON", "vix_level": 15.2 } }
```

---

## ➕ Adding a New Broker

1. Create `brokers/your_broker.py`
2. Subclass `BaseBroker` and implement all abstract methods
3. In `orchestrator.py`, replace `AlpacaBroker` with your new class

```python
# brokers/ibkr_broker.py
from brokers.base_broker import BaseBroker, BrokerMode

class IBKRBroker(BaseBroker):
    def __init__(self, mode: BrokerMode):
        super().__init__(mode)
        # connect to IBKR TWS / IB Gateway

    async def get_account(self) -> AccountInfo: ...
    async def submit_bracket_order(self, ...) -> OrderResult: ...
    # ... implement all 10 abstract methods
```

---

## ⚠️ Risk Disclaimer

This software is for **educational and research purposes only**.
- Live trading involves real financial risk
- Past performance of any strategy does not guarantee future results
- Always start with paper trading, validate strategy, then scale slowly
- The authors are not responsible for financial losses

---

## 📈 Roadmap

- [ ] WebSocket equity curve chart (recharts)
- [ ] Multi-day backtesting mode
- [ ] Strategy performance analytics
- [ ] Discord / Slack trade alerts
- [ ] IBKR broker adapter
- [ ] Coinbase adapter for crypto
- [ ] Docker Compose deployment
- [ ] Prometheus metrics + Grafana dashboard
