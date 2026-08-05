# PolySignal Pro

**Polymarket Prediction Market Intelligence System**

A research-first, paper trading, risk-controlled system for analyzing Polymarket prediction markets.

---

## ⚠️ Important Disclaimers

**This system is NOT:**
- A get-rich-quick script
- A guaranteed profit bot
- An automated copy-trading system
- An LLM autonomous trading system
- A high-frequency trading system

**This system IS:**
- A research platform for prediction market analysis
- A paper trading simulation tool
- A risk-controlled signal generation system
- A long-term strategy validation framework

**Default Mode: READ-ONLY + PAPER TRADING**

Live trading is **DISABLED** by default and requires explicit configuration.

---

## Features

- **Data Provider Manager**: Supports mock, real_readonly, and hybrid modes
- **Gamma API Client**: Fetch real market data from Polymarket
- **CLOB REST Client**: Fetch real orderbook data (read-only)
- **Market Microstructure Engine**: Analyze orderbook spread, depth, imbalance
- **YES/NO Mispricing Detection**: Detect combined ask arbitrage opportunities
- **Resolution & Lifecycle Engine**: Track market lifecycle and resolution risk
- **Wallet Intelligence Engine**: Analyze wallet behavior and copy risk
- **Event Intelligence Engine**: Assess event relevance and ambiguity
- **Risk Governor**: Central risk control with hard rejection conditions
- **Paper Trader**: Simulate trading for strategy validation
- **Telegram Signal Cockpit**: Monitoring and control panel
- **SQLite Storage**: Persistent logging for all signals and trades
- **CLI + Streamlit Dashboard**: Read-only system and research summaries
- **Local Web Console**: Responsive, read-only v7 cohort and safety review
- **Crypto Threshold Shadow Validation**: Run-scoped, side-specific corrected PnL research

---

## Quick Start

### Prerequisites

- Python 3.9+
- pip or uv

### Installation

```bash
# Clone repository
git clone <repository-url>
cd PolySignal-Pro

# Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies required by the full test suite and dashboard
pip install -e ".[dev,dashboard]"

# Equivalent uv workflow
uv sync --extra dev --extra dashboard
```

### Configuration

1. Copy `.env.example` to `.env`:
   ```bash
   cp .env.example .env
   ```

2. **DO NOT** modify `LIVE_TRADING_ENABLED` - it must remain `false`

3. Optionally configure Telegram (for alerts):
   ```
   TELEGRAM_BOT_TOKEN=your_token
   TELEGRAM_CHAT_ID=your_chat_id
   ```

### Run

```bash
# Run main application (mock mode by default)
python -m polysignal.main

# Or use CLI
polysignal
```

### Local Web Console

The project also includes a compact, read-only browser console for reviewing the
latest v7 shadow-validation artifacts:

```bash
uv run python scripts/run_web_console.py --port 8502
```

Open <http://127.0.0.1:8502>. The server is loopback-only by default. It reads
run-scoped JSON plus the non-secret safety configuration, does not load `.env`,
make network or LLM calls, and exposes no order, signing, or mutation endpoint.
It never writes to `runs/` or `config/`; restart or use the refresh control to
read a newer snapshot.

### Data Modes

The system supports three data modes:

| Mode | Description |
|------|-------------|
| `mock` | Uses simulated data (default) |
| `real_readonly` | Uses real Polymarket API (read-only) |
| `hybrid` | Tries real API first, falls back to mock |

Set via environment variable:
```bash
DATA_MODE=mock  # or real_readonly or hybrid
```

### Real Read-only Smoke Test

To test with real Polymarket API (read-only):

```bash
# Run smoke test with real API
python scripts/smoke_real_readonly.py
```

This script:
- Fetches real markets from Gamma API
- Fetches real orderbooks from CLOB REST API
- Runs data through the full pipeline
- Simulates paper trades (no real orders)

**Important**: This script does NOT place real orders and does NOT require private keys.

---

### Crypto Threshold Shadow Validation

Use a new run directory for every discovery snapshot. The commands below remain public,
read-only, and shadow-only:

```bash
RUN_DIR=runs/crypto_threshold_shadow/step12_<run_id>

python scripts/discover_crypto_threshold_edges.py \
  --max_markets 3000 \
  --output_dir "$RUN_DIR/discovery" \
  --avoid_candidates_file runs/avoid_candidates.csv

python scripts/validate_crypto_threshold_shadow_pnl.py \
  --candidate_file "$RUN_DIR/discovery/crypto_threshold_edge_candidates.csv" \
  --avoid_file runs/avoid_candidates.csv \
  --output_dir "$RUN_DIR/validation"

# Run the poller only when validator positions_created > 0.
```

The validator uses the v7 contract and accepts only discovery schema v5/parser v4.
`resolution_source_adapter_v1` accepts a structured Gamma
source or one unique HTTPS URL inside an explicit resolution-source section. It trusts exact
allowlisted hosts only; HTTP, multiple URLs, non-string fields, source conflicts, and untrusted
hosts fail closed. Binance sources additionally require the candidate asset, `ASSET/USDT` pair,
one-minute interval, and `High`/`Low` rule semantics to agree. Origin, locator, adapter version,
rules SHA-256, and a provenance digest are persisted. Non-Binance sources must also match exactly
one provider and asset in both the URL and rule prose.

`gamma_expiry_adapter_v1` converts the title-local 23:59 cutoff using the explicit rules timezone
and corroborates it against Gamma `endDate`; ambiguous, naive, conflicting, or mismatched evidence
fails closed. The stable trade identity binds expiry/source provenance, spot, all client/server
timestamps, four prices, four sizes, tokens, notional/shares, and gate fields. Existing prepared
input is preserved under a content-addressed immutable filename before output replacement.

Latest read-only run `step12_v7_20260804_140305` scanned 1,958 Gamma markets, detected 56 crypto
markets, and parsed 44 threshold candidates. Discovery v5 committed one exact-minute batch entry,
used three asset-level historical preloads plus three entry tails, and wrote three shared candle
snapshots with 43 threshold-specific evidence manifests. Historical coverage verified 43/44; the
remaining market has no rules-defined barrier start and remains fail-closed. Three public CLOB
book reads were incomplete, so discovery recorded 12 shadow entries and 32 watch-only rows without
inventing quotes.

Validator v7 independently accepted 11 fresh positions across BTC/ETH/SOL and three correlated
clusters. All 11 currently lack a qualifying >=240-minute forward observation, so closed positions
are zero, PnL and win rate are null, and status is `insufficient_forward_data`. This is pipeline
evidence, not an edge or profitability result. Gamma recorded one recoverable terminal pagination
error, so the scan is not claimed as exhaustive.

The v5 run `step12_v5_20260804_073542` and all earlier runs are audit-only: v5 used the wrong
ET/UTC cutoff, lacked historical barrier evidence, did not bind the complete entry identity, and
did not validate the full forward book. Do not poll, migrate, supplement, or use them for PnL.
The next research step is to collect qualifying forward observations after the 240-minute horizon
and expand beyond three independent clusters. `tiny_live_recommendation` remains `NO`.

The restricted container profile is opt-in and keeps the root filesystem read-only, drops all
capabilities, runs as UID/GID 10001, and forces live/automatic execution off:

```bash
docker compose --profile research run --rm research \
  python scripts/discover_crypto_threshold_edges.py --help
```

On native Linux, ensure bind-mounted `runs/`, `data/`, and `logs/` directories are writable by UID
10001 before using the corresponding service. No `.env` file is copied into the image.

The current single-leg PaperTrader rejects `SignalSide.BOTH` until typed two-leg positions,
independent leg ledgers, and non-atomic leg-risk handling are implemented.

---

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                    Data Ingestion                        │
│  Mock / Real Read-only REST / Read-only WebSocket       │
└─────────────────────────────────────────────────────────┘
                           ↓
┌─────────────────────────────────────────────────────────┐
│                    Intelligence Engines                  │
│  Market Microstructure | Wallet | Event | Lifecycle     │
└─────────────────────────────────────────────────────────┘
                           ↓
┌─────────────────────────────────────────────────────────┐
│                    Risk Governor                         │
│  Hard Rejection | Score Calculation | Action Decision   │
└─────────────────────────────────────────────────────────┘
                           ↓
┌─────────────────────────────────────────────────────────┐
│                    Execution Layer                       │
│  Paper Trader (MVP) | Live Trader Stub                  │
└─────────────────────────────────────────────────────────┘
                           ↓
┌─────────────────────────────────────────────────────────┐
│                    Storage & Interface                   │
│  SQLite | CLI Dashboard | Telegram (Optional)          │
└─────────────────────────────────────────────────────────┘
```

---

## Testing

```bash
# Run all tests in the declared environment
uv run pytest -q

# Current full verification: 1762 passed in 267.29s
```

**Test Coverage:**
- Config loading and validation
- Data Provider Manager (mock / real_readonly / hybrid)
- Gamma API Client
- CLOB REST Client
- Data Converter
- Market Microstructure Engine
- Resolution & Lifecycle Engine
- Wallet Intelligence Engine
- Event Intelligence Engine
- YES/NO Mispricing Strategy
- Risk Governor (hard rejection, score calculation, thresholds)
- Paper Trader (execution, tracking, PnL)
- Telegram Signal Cockpit

**Note**: All tests use mock HTTP responses. Tests do NOT depend on real Polymarket API.

---

## Safety Guarantees

| Guarantee | Implementation |
|-----------|----------------|
| Live trading disabled | `live_trading_enabled: false` in config/risk.yaml |
| Auto execution disabled | `allow_auto_execution: false` in config/risk.yaml |
| Paper trading enabled | `paper_trading_enabled: true` in config/risk.yaml |
| LLM cannot order | LLM only outputs analysis |
| Risk Governor required | All signals must pass Risk Governor |
| No real private keys | Read-only and shadow paths require no private key |
| Paper trading only | Live trader is stub |
| Ultra-fast path no LLM | YES/NO mispricing strategy does not call LLM |
| Side-specific depth check | Risk Governor checks depth based on signal side |
| Real API read-only | No POST/DELETE endpoints, no authentication |
| No order placement | Smoke test uses read-only endpoints only |

---

## Project Structure

```
PolySignal-Pro/
├── config/           # Configuration files
├── polysignal/       # Main package
│   ├── models/       # Pydantic data models
│   ├── ingestion/    # Data providers
│   ├── engines/      # Intelligence engines
│   ├── strategies/   # Trading strategies
│   ├── risk/         # Risk management
│   ├── execution/    # Order execution
│   ├── storage/      # Database
│   └── interface/    # CLI / Dashboard
├── tests/            # Test suite
└── docs/             # Documentation
```

---

## Milestone Status

| Milestone | Status | Description |
|-----------|--------|-------------|
| M1 | ✅ Completed | Read-only + Paper Trading MVP |
| M1.5 | ✅ Completed | Engineering Audit & Deliverable Cleanup |
| M2A | ✅ Completed | Resolution & Lifecycle Engine |
| M2B | ✅ Completed | Wallet Intelligence Engine |
| M2C | ✅ Completed | Event Intelligence + Mock LLM |
| M3 | ✅ Completed | Telegram Signal Cockpit |
| Phase 4A | ✅ Completed | Real Read-only Polymarket API (REST) |
| Phase 4A.5 | ✅ Completed | Real Read-only Smoke Test |
| Phase 4B | ✅ Completed | CLOB WebSocket read-only |
| Trading MVP Step 12 | ⏳ Forward data pending | v7 historical evidence complete; 11 paper positions; 0 closed |
| M5 | 🔮 Optional | Tiny Live Limit Order |

---

## License

MIT License - See LICENSE file for details.

---

## Contributing

This project follows strict safety guidelines. All contributions must:
- Keep `live_trading_enabled` default `false`
- Not bypass Risk Governor
- Include tests for core modules
- Follow coding standards in `docs/coding_standard.md`

---

## Risk Warning

**Trading prediction markets involves risk.**

This system is designed for **research purposes only**. Paper trading results do not guarantee real trading performance. Market conditions, liquidity, and execution can differ significantly between simulation and reality.

**Never enable live trading without:**
1. Understanding all risk parameters
2. Testing extensively with paper trading
3. Using only small test amounts
4. Manual confirmation for each trade

---

## Documentation

- [CLAUDE.md](CLAUDE.md) - Claude Code engineering guidelines
- [SPEC.md](SPEC.md) - Product specification
- [AGENTS.md](AGENTS.md) - Agent team coordination
- [docs/coding_standard.md](docs/coding_standard.md) - Coding standards
- [docs/risk_policy.md](docs/risk_policy.md) - Risk policy
- [docs/architecture_decisions.md](docs/architecture_decisions.md) - Architecture decisions
- [docs/phase_4_api.md](docs/phase_4_api.md) - Phase 4 API integration guide
