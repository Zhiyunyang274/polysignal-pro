# Phase 5A — 30-Minute Dry Run

## Overview

Phase 5A implements a 30-minute paper trading dry run capability for PolySignal Pro. This is the first of three phases:

- **Phase 5A**: 30-minute dry run (default)
- **Phase 5B**: 3-hour paper trading run
- **Phase 5C**: 24-hour paper trading run

## Safety Guarantees

The paper trading runner enforces strict safety constraints:

1. **live_trading_enabled must be false** - No real orders can be placed
2. **allow_auto_execution must be false** - No automatic live execution
3. **paper_trading_enabled must be true** - Only paper trading allowed
4. **No private keys required** - No wallet connection needed
5. **Real LLM requires explicit limit** - Must set `--max_llm_calls_per_hour > 0`

## Conservative Defaults

```yaml
duration_minutes: 30
duration_hours: 0.5
max_markets: 10
scan_interval_seconds: 120
data_mode: hybrid
llm_provider: mock
max_llm_calls_per_hour: 0
max_signals_per_hour: 20
telegram_enabled: false
max_telegram_messages_per_hour: 0
```

## Usage

### Basic 30-Minute Dry Run

```bash
# Default 30-minute run with mock data
python3 scripts/run_paper.py
```

### 3-Hour Run

```bash
python3 scripts/run_paper.py --duration_hours 3
```

### 24-Hour Run

```bash
python3 scripts/run_paper.py --duration_hours 24
```

### With Real LLM

```bash
# Real LLM requires explicit call limit
python3 scripts/run_paper.py \
    --llm_provider xfyun_anthropic \
    --max_llm_calls_per_hour 10
```

### With Real Data API

```bash
python3 scripts/run_paper.py \
    --data_mode real_readonly \
    --use_websocket true
```

### With Telegram Alerts

```bash
python3 scripts/run_paper.py \
    --telegram_enabled true \
    --max_telegram_messages_per_hour 5
```

## Command Line Arguments

| Argument | Default | Description |
|----------|---------|-------------|
| `--duration_minutes` | 30 | Duration in minutes |
| `--duration_hours` | - | Duration in hours (overrides minutes) |
| `--max_markets` | 10 | Maximum markets to monitor |
| `--scan_interval_seconds` | 120 | Scan interval in seconds |
| `--data_mode` | hybrid | Data mode: mock, real_readonly, hybrid |
| `--use_websocket` | true | Use WebSocket for real-time data |
| `--llm_provider` | mock | LLM provider: mock, xfyun_anthropic, sensenova |
| `--max_llm_calls_per_hour` | 0 | Maximum LLM calls per hour |
| `--max_signals_per_hour` | 20 | Maximum signals per hour |
| `--telegram_enabled` | false | Enable Telegram alerts |
| `--max_telegram_messages_per_hour` | 0 | Maximum Telegram messages per hour |

## Output Files

Each run creates a directory under `runs/<run_id>/`:

```
runs/
└── run_20260508_120000_abc12345/
    ├── summary.json      # JSON summary
    ├── report.md         # Markdown report
    └── events.jsonl      # Event log (JSONL)
```

### summary.json

Contains complete run statistics:

```json
{
  "run_id": "run_20260508_120000_abc12345",
  "status": "completed",
  "start_time": "2026-05-08T12:00:00",
  "end_time": "2026-05-08T12:30:00",
  "duration_minutes": 30,
  "markets_checked": 150,
  "signals_generated": 25,
  "signals_paper_trade": 5,
  ...
}
```

### report.md

Human-readable markdown report with:
- Run summary
- Configuration
- Statistics
- LLM performance
- API/WebSocket stats
- Hard reject reasons
- Safety verification

### events.jsonl

Line-delimited JSON events:

```json
{"event_id": "...", "event_type": "run_start", ...}
{"event_id": "...", "event_type": "scan_start", ...}
{"event_id": "...", "event_type": "scan_end", ...}
{"event_id": "...", "event_type": "run_end", ...}
```

## Database Tables

Phase 5A adds three new SQLite tables:

### paper_runs

Main run tracking table:

```sql
CREATE TABLE paper_runs (
    run_id TEXT PRIMARY KEY,
    start_time TEXT NOT NULL,
    end_time TEXT,
    status TEXT NOT NULL DEFAULT 'running',
    duration_minutes INTEGER,
    duration_hours REAL,
    -- Configuration
    data_mode TEXT NOT NULL,
    llm_provider TEXT NOT NULL,
    websocket_enabled INTEGER NOT NULL,
    telegram_enabled INTEGER NOT NULL,
    max_markets INTEGER,
    scan_interval_seconds INTEGER,
    max_llm_calls_per_hour INTEGER,
    max_signals_per_hour INTEGER,
    max_telegram_messages_per_hour INTEGER,
    -- Statistics
    markets_checked INTEGER DEFAULT 0,
    signals_generated INTEGER DEFAULT 0,
    ...
);
```

### paper_run_scans

Per-scan tracking:

```sql
CREATE TABLE paper_run_scans (
    scan_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    scan_time TEXT NOT NULL,
    markets_scanned INTEGER DEFAULT 0,
    signals_generated INTEGER DEFAULT 0,
    ...
);
```

### paper_run_events

Event log:

```sql
CREATE TABLE paper_run_events (
    event_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    event_time TEXT NOT NULL,
    event_type TEXT NOT NULL,
    event_category TEXT NOT NULL,
    description TEXT,
    details TEXT,
    ...
);
```

## Rate Limiting

The runner enforces hourly rate limits:

- **LLM calls**: Reset every hour, configurable via `--max_llm_calls_per_hour`
- **Signals**: Reset every hour, configurable via `--max_signals_per_hour`
- **Telegram messages**: Reset every hour, configurable via `--max_telegram_messages_per_hour`

## Graceful Shutdown

The runner supports graceful shutdown via signals:

- **SIGINT** (Ctrl+C): Initiates graceful shutdown
- **SIGTERM**: Initiates graceful shutdown

On shutdown:
1. Current scan completes
2. Run statistics saved to database
3. Reports generated
4. Database connection closed

## Safety Verification

Every run includes safety verification in the report:

```markdown
## Safety Verification

- ✅ live_trading_enabled: false
- ✅ allow_auto_execution: false
- ✅ paper_trading_enabled: true
- ✅ No real orders placed
- ✅ No private keys used
```

## Test Coverage

See `tests/test_paper_run.py` for comprehensive test coverage:

- Runner initialization
- Safety checks
- Conservative default config
- Run ID generation
- Report file creation
- Rate limits
- LLM call limit
- Telegram disabled by default
- Graceful shutdown
- API fallback
- No live trading path
- No private key requirement

## Running Tests

```bash
pytest tests/test_paper_run.py -v
```

## Next Steps

After successful Phase 5A dry run:

1. Review `runs/<run_id>/report.md`
2. Check `summary.json` for statistics
3. Analyze `events.jsonl` for detailed event log
4. Verify safety constraints in report
5. Proceed to Phase 5B (3-hour run) if satisfied

## Troubleshooting

### Safety Check Failed

If safety checks fail, check your configuration:

```bash
# Verify live_trading_enabled is false
grep live_trading_enabled config/risk.yaml

# Verify allow_auto_execution is false
grep allow_auto_execution config/risk.yaml
```

### Real LLM Without Limit

If using real LLM, you must set a call limit:

```bash
# Correct usage
python3 scripts/run_paper.py \
    --llm_provider xfyun_anthropic \
    --max_llm_calls_per_hour 10
```

### Database Errors

If database errors occur, ensure directory exists:

```bash
mkdir -p data
```

## References

- [ROADMAP.md](../ROADMAP.md) - Project roadmap
- [TASKS.md](../TASKS.md) - Current tasks
- [CONTEXT.md](../CONTEXT.md) - Project context
- [SPEC.md](../SPEC.md) - System specification
